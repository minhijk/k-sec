# db_handler_es.py (메모리 관리 강화 버전 - psutil 제거)

import yaml
import subprocess
import json
import os
import sys
import uuid
import time
import gc
from langchain.retrievers import EnsembleRetriever
from langchain_elasticsearch import ElasticsearchStore, ElasticsearchRetriever
from langchain_huggingface import HuggingFaceEmbeddings

# --- 설정 변수 ---
ELASTIC_URL = os.getenv("ELASTIC_URL", "http://localhost:9200")
INDEX_NAME = os.getenv("INDEX_NAME", "k8s_security_documents")
MODEL_NAME = os.getenv("MODEL_NAME", "jhgan/ko-sroberta-multitask")

# --- 전역 임베딩 모델 (한 번만 로드) ---
print(f"[INIT] 임베딩 모델 로드 중... ({MODEL_NAME})")
EMBEDDING_MODEL = None
try:
    EMBEDDING_MODEL = HuggingFaceEmbeddings(
        model_name=MODEL_NAME,
        model_kwargs={'device': 'cpu'},
        encode_kwargs={'normalize_embeddings': True}
    )
    print("[INIT] ✅ 임베딩 모델 로드 성공!")
except Exception as e:
    print(f"[INIT] ❌ 임베딩 모델 로드 실패: {e}")

# --- 전역 Elasticsearch 연결 ---
VECTOR_STORE = None
ENSEMBLE_RETRIEVER = None


def cleanup_resources():
    """전역 리소스를 해제하고 메모리를 정리합니다"""
    global VECTOR_STORE, ENSEMBLE_RETRIEVER
    
    if VECTOR_STORE:
        try:
            if hasattr(VECTOR_STORE, 'client'):
                VECTOR_STORE.client.close()
            VECTOR_STORE = None
        except Exception as e:
            pass
    
    if ENSEMBLE_RETRIEVER:
        ENSEMBLE_RETRIEVER = None
    
    gc.collect()


def initialize_elasticsearch():
    """Elasticsearch 연결을 초기화합니다 (최초 1회만 실행)"""
    global VECTOR_STORE, ENSEMBLE_RETRIEVER
    
    if ENSEMBLE_RETRIEVER is not None:
        return True
    
    try:
        print(f"[INIT] Elasticsearch 연결 중... ({ELASTIC_URL})")
        VECTOR_STORE = ElasticsearchStore(
            es_url=ELASTIC_URL,
            index_name=INDEX_NAME,
            embedding=EMBEDDING_MODEL,
        )
        
        def bm25_query_builder(query_text: str):
            return {
                "query": {"match": {"text": query_text}},
                "_source": {"excludes": ["vector"]}
            }
        
        keyword_retriever = ElasticsearchRetriever(
            es_client=VECTOR_STORE.client,
            index_name=INDEX_NAME,
            body_func=bm25_query_builder,
            content_field="text"
        )
        
        vector_retriever = VECTOR_STORE.as_retriever(
            search_kwargs={'k': 1, "_source_excludes": ["vector"]}
        )
        
        ENSEMBLE_RETRIEVER = EnsembleRetriever(
            retrievers=[keyword_retriever, vector_retriever],
            weights=[0.5, 0.5]
        )
        
        print("[INIT] ✅ Elasticsearch 연결 및 Retriever 초기화 성공!")
        return True
        
    except Exception as e:
        print(f"[INIT] ❌ Elasticsearch 초기화 실패: {e}")
        return False


# 서버 시작 시 Elasticsearch 초기화 시도
initialize_elasticsearch()


def run_trivy_scan(yaml_content: str) -> dict:
    """Trivy를 사용하여 YAML 파일을 스캔합니다."""
    start_time = time.time()
    command = ['trivy', 'config', '--format', 'json', '-']
    
    try:
        print(f"[TRIVY] 스캔 시작 (stdin)...")
        result = subprocess.run(
            command, input=yaml_content, capture_output=True,
            text=True, check=True, encoding='utf-8', timeout=15
        )
        elapsed = time.time() - start_time
        print(f"[TRIVY] ✅ 스캔 완료 ({elapsed:.2f}초)")
        return json.loads(result.stdout)
        
    except subprocess.TimeoutExpired:
        print(f"[TRIVY] stdin 방식 타임아웃, 파일 방식으로 재시도...")
        
    except Exception as e:
        print(f"[TRIVY] stdin 방식 실패: {e}, 파일 방식으로 재시도...")
    
    # 임시 파일 방식으로 재시도
    temp_file_name = f"temp_scan_{uuid.uuid4()}.yaml"
    try:
        with open(temp_file_name, 'w', encoding='utf-8') as f:
            f.write(yaml_content)
        
        command = ['trivy', 'config', '--format', 'json', temp_file_name]
        print(f"[TRIVY] 스캔 재시도 (file)...")
        result = subprocess.run(
            command, capture_output=True, text=True, 
            check=True, encoding='utf-8', timeout=15
        )
        elapsed = time.time() - start_time
        print(f"[TRIVY] ✅ 스캔 완료 ({elapsed:.2f}초)")
        return json.loads(result.stdout)
        
    except Exception as e2:
        print(f"[TRIVY] ❌ 최종 실패: {e2}")
        return None
        
    finally:
        if os.path.exists(temp_file_name):
            os.remove(temp_file_name)


def extract_queries_from_trivy_results(trivy_json: dict) -> list[str]:
    """Trivy 스캔 결과에서 RAG 검색을 위한 쿼리를 추출합니다."""
    queries = []
    if not trivy_json or 'Results' not in trivy_json: 
        return queries
    
    for result in trivy_json.get('Results', []):
        for misconfig in result.get('Misconfigurations', []):
            title = misconfig.get('Title', '')
            misconfig_id = misconfig.get('ID', '')
            description = misconfig.get('Description', '')
            resolution = misconfig.get('Resolution', '')
            
            enhanced_query = f"{misconfig_id}: {title}. {description}. {resolution}"
            queries.append(enhanced_query)
            
    return list(set(queries))


def get_trivy_and_rag_analysis(yaml_content: str):
    """YAML 파일에 대한 Trivy 스캔 및 RAG 분석을 수행합니다."""
    total_start = time.time()
    
    print("\n" + "="*70)
    print("[ANALYSIS] 분석 시작...")
    
    # Elasticsearch 연결 확인
    if not ENSEMBLE_RETRIEVER:
        if not initialize_elasticsearch():
            return {"error": "Elasticsearch 연결 실패. 서버가 실행 중인지 확인하세요."}
    
    # Trivy 스캔 실행
    print("[STEP 1/3] Trivy 보안 스캔 실행 중...")
    trivy_results = run_trivy_scan(yaml_content)
    
    if not trivy_results:
        return {"error": "Trivy 스캔에 실패했습니다."}
    
    # Trivy 결과에서 쿼리 추출
    security_queries = extract_queries_from_trivy_results(trivy_results)
    
    if not security_queries:
        print("[INFO] 보안 문제점이 발견되지 않았습니다.")
        return 0
    
    print(f"[STEP 2/3] {len(security_queries)}개의 보안 이슈 발견")
    
    # RAG 검색 수행
    print(f"[STEP 3/3] RAG 검색 수행 중 ({len(security_queries)}개 쿼리)...")
    rag_start = time.time()
    
    unique_docs_with_queries = {}
    
    for idx, query in enumerate(security_queries, 1):
        try:
            print(f"  [{idx}/{len(security_queries)}] 검색 중...", end='\r')
            retrieved_docs = ENSEMBLE_RETRIEVER.invoke(query)
            
            if retrieved_docs:
                doc = retrieved_docs[0]
                doc_content_key = doc.page_content
                
                if doc_content_key not in unique_docs_with_queries:
                    unique_docs_with_queries[doc_content_key] = {
                        'doc': doc, 
                        'queries': [query]
                    }
                else:
                    unique_docs_with_queries[doc_content_key]['queries'].append(query)
                    
        except Exception as e:
            print(f"\n[WARN] 쿼리 '{query[:50]}...' 검색 실패: {e}")
            continue
    
    rag_elapsed = time.time() - rag_start
    print(f"\n[RAG] ✅ 검색 완료 ({rag_elapsed:.2f}초, {len(unique_docs_with_queries)}개 문서)")
    
    # 결과 정리
    analysis_results_list = []
    for item in unique_docs_with_queries.values():
        doc, queries = item['doc'], sorted(item['queries'])
        analysis_results_list.append({
            "retrieved_for_queries": queries,
            "source_document": {
                "content": doc.page_content, 
                "metadata": doc.metadata
            }
        })
    
    analysis_results_list.sort(
        key=lambda x: x['source_document']['metadata'].get('id', '')
    )
    
    total_elapsed = time.time() - total_start
    
    print(f"[ANALYSIS] ✅ 전체 분석 완료 ({total_elapsed:.2f}초)")
    print("="*70 + "\n")
    
    return {
        "analyzed_yaml_content": yaml_content,
        "trivy_scan_summary": {
            "total_queries_generated": len(security_queries),
            "unique_documents_found": len(analysis_results_list)
        },
        "analysis_results": analysis_results_list,
    }


def shutdown_handler():
    """서버 종료 시 호출되어 리소스를 정리합니다"""
    cleanup_resources()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"사용법: python {sys.argv[0]} <분석할_YAML_파일_경로>")
        sys.exit(1)
    
    yaml_file_path = sys.argv[1]
    if not os.path.exists(yaml_file_path):
        print(f"[ERROR] 파일을 찾을 수 없습니다: {yaml_file_path}")
        sys.exit(1)

    with open(yaml_file_path, 'r', encoding='utf-8') as f:
        yaml_content = f.read()
    
    result = get_trivy_and_rag_analysis(yaml_content)

    if isinstance(result, int) and result == 0:
        print("\n✅ 분석 결과: 보안 문제점이 발견되지 않았습니다.")
    elif 'error' in result:
        print(f"\n❌ [ERROR] {result['error']}")
    else:
        output_filename = "result.txt"
        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ 분석 완료! 결과가 '{output_filename}' 파일에 저장되었습니다.")
    
    shutdown_handler()