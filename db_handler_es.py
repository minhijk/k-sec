# db_handler_es.py

import yaml
import subprocess
import json
import os
import sys
import uuid
from langchain.retrievers import EnsembleRetriever
from langchain_elasticsearch import ElasticsearchStore, ElasticsearchRetriever
from langchain_huggingface import HuggingFaceEmbeddings

# --- 설정 변수 ---
ELASTIC_URL = "http://localhost:9200"
INDEX_NAME = "k8s_security_documents"
MODEL_NAME = "jhgan/ko-sroberta-multitask"

# --- 함수 정의 ---

def run_trivy_scan(yaml_content: str) -> dict:
    command = ['trivy', 'config', '--format', 'json', '-']
    try:
        print(f" -> Trivy 스캔 실행 (stdin): {' '.join(command)}")
        result = subprocess.run(
            command, input=yaml_content, capture_output=True,
            text=True, check=True, encoding='utf-8'
        )
        return json.loads(result.stdout)
    except Exception as e:
        print(f"[알림] stdin 방식 스캔 실패, 임시 파일 방식으로 재시도합니다. 오류: {e}")
        temp_file_name = f"temp_scan_{uuid.uuid4()}.yaml"
        try:
            with open(temp_file_name, 'w', encoding='utf-8') as f:
                f.write(yaml_content)
            command = ['trivy', 'config', '--format', 'json', temp_file_name]
            print(f" -> Trivy 스캔 실행 (file): {' '.join(command)}")
            result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
            return json.loads(result.stdout)
        except Exception as e2:
            print(f"\n[오류] Trivy 스캔 중 최종 오류 발생: {e2}")
            return None
        finally:
            if os.path.exists(temp_file_name):
                os.remove(temp_file_name)


def extract_queries_from_trivy_results(trivy_json: dict) -> list[str]:
    queries = []
    if not trivy_json or 'Results' not in trivy_json: return queries
    for result in trivy_json.get('Results', []):
        for misconfig in result.get('Misconfigurations', []):
            # Title, ID, Description을 조합하여 훨씬 상세한 쿼리 생성
            title = misconfig.get('Title', '')
            misconfig_id = misconfig.get('ID', '')
            description = misconfig.get('Description', '')
            resolution = misconfig.get('Resolution', '')

            # 더 많은 정보를 담은 새로운 쿼리
            enhanced_query = f"{misconfig_id}: {title}. {description}. {resolution}"
            
            queries.append(enhanced_query)
            
    return list(set(queries))

def get_trivy_and_rag_analysis(yaml_content: str):
    trivy_results = run_trivy_scan(yaml_content)
    if not trivy_results:
        return {"error": "Trivy 스캔에 실패했거나 결과가 없습니다."}
    
    security_queries = extract_queries_from_trivy_results(trivy_results)
    
    if not security_queries:
        return 0

    print("[DEBUG] 임베딩 모델 로드 중...")
    embedding_model = HuggingFaceEmbeddings(model_name=MODEL_NAME)
    
    print(f"[DEBUG] Elasticsearch DB ('{INDEX_NAME}' 인덱스) 연결 시도...")
    try:
        vector_db = ElasticsearchStore(
            es_url=ELASTIC_URL,
            index_name=INDEX_NAME,
            embedding=embedding_model,
        )
        print("[DEBUG] Elasticsearch DB 연결 완료.")
    except Exception as e:
        return {"error": f"Elasticsearch 연결 실패: {e}"}

    # ==================== [하이브리드 검색 로직 최종 수정] ====================

    # 1. 키워드 검색(BM25)을 위한 쿼리 생성 함수 수정
    def bm25_query_builder(query_text: str):
        return {
            "query": {
                "match": {
                    "text": query_text
                }
            },
            # 여기에 _source 옵션을 직접 추가하여 vector 필드를 제외합니다.
            "_source": {
                "excludes": ["vector"]
            }
        }

    # 2. 키워드 검색기(BM25) 생성 - 올바른 파라미터 사용
    keyword_retriever = ElasticsearchRetriever(
        es_client=vector_db.client,
        index_name=INDEX_NAME,
        body_func=bm25_query_builder,
        content_field="text"
    )

    # 3. 벡터 검색기(유사도) 생성 - 여기서는 search_kwargs를 사용합니다.
    vector_retriever = vector_db.as_retriever(
        search_kwargs={'k': 1, "_source_excludes": ["vector"]}
    )

    # 4. EnsembleRetriever로 두 검색기를 조합
    ensemble_retriever = EnsembleRetriever(
        retrievers=[keyword_retriever, vector_retriever],
        weights=[0.5, 0.5]
    )
    # ======================================================================

    unique_docs_with_queries = {}
    print("[DEBUG] RAG 검색 시작 (앙상블 하이브리드 모드)...")
    for query in security_queries:
        retrieved_docs = ensemble_retriever.invoke(query)
        if retrieved_docs:
            doc = retrieved_docs[0]
            doc_content_key = doc.page_content
            if doc_content_key not in unique_docs_with_queries:
                unique_docs_with_queries[doc_content_key] = {'doc': doc, 'queries': [query]}
            else:
                unique_docs_with_queries[doc_content_key]['queries'].append(query)
    print("[DEBUG] RAG 검색 완료.")

    analysis_results_list = []
    for item in unique_docs_with_queries.values():
        doc, queries = item['doc'], sorted(item['queries'])
        analysis_results_list.append({
            "retrieved_for_queries": queries,
            "source_document": {"content": doc.page_content, "metadata": doc.metadata}
        })
    analysis_results_list.sort(key=lambda x: x['source_document']['metadata'].get('id', ''))

    return {
        "analyzed_yaml_content": yaml_content,
        "trivy_scan_summary": {
            "total_queries_generated": len(security_queries),
            "unique_documents_found": len(analysis_results_list)
        },
        "analysis_results": analysis_results_list,
    }

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"사용법: python {sys.argv[0]} <분석할_YAML_파일_경로>")
        sys.exit(1)
    
    yaml_file_path = sys.argv[1]
    if not os.path.exists(yaml_file_path):
        print(f"[오류] 파일을 찾을 수 없습니다: {yaml_file_path}")
        sys.exit(1)

    with open(yaml_file_path, 'r', encoding='utf-8') as f:
        yaml_content = f.read()
    
    result = get_trivy_and_rag_analysis(yaml_content)

    if isinstance(result, int) and result == 0:
        print("\n분석 결과: 보안 문제점이 발견되지 않았습니다.")
    elif 'error' in result:
        print(f"\n[오류] 분석 중 문제가 발생했습니다: {result['error']}")
    else:
        output_filename = "result.txt"
        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print("\n" + "="*28 + " [분석 완료] " + "="*28)
        print(f"[최종 분석 결과]가 '{output_filename}' 파일에 저장되었습니다.")
        print("\n" + "="*70)