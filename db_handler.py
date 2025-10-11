import yaml
import subprocess
import json
import tempfile
import os
import sys
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# --- 설정 변수 ---
DB_PATH = "./chroma_db_precomputed"
COLLECTION_NAME = "my_precomputed_db"
MODEL_NAME = "jhgan/ko-sroberta-multitask"

# --- Trivy 스캔 함수 ---
def run_trivy_scan(file_path: str) -> dict:
    """Trivy를 실행하여 YAML 설정 파일의 취약점을 스캔하고 결과를 JSON으로 반환"""
    command = ['trivy', 'config', '--format', 'json', file_path]
    try:
        print(f" -> Trivy 스캔 실행: {' '.join(command)}")
        result = subprocess.run(
            command, capture_output=True, text=True, check=True, encoding='utf-8'
        )
        return json.loads(result.stdout)
    except FileNotFoundError:
        print("\n[오류] 'trivy' 명령어를 찾을 수 없습니다.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"\n[오류] Trivy 스캔 중 오류 발생: {e.stderr}")
        return None
    except json.JSONDecodeError:
        print("\n[오류] Trivy 출력 결과를 JSON으로 파싱하는 데 실패했습니다.")
        return None

def extract_structured_findings(trivy_json: dict) -> list[dict]:
    """ [새로운 함수] Trivy 결과에서 LLM에게 제공할 구조화된 정보를 추출합니다. """
    findings = []
    if not trivy_json or 'Results' not in trivy_json:
        return findings
    for result in trivy_json.get('Results', []):
        for misconfig in result.get('Misconfigurations', []):
            if misconfig.get('Status') == 'FAIL':
                findings.append({
                    "id": misconfig.get('ID'),
                    "title": misconfig.get('Title'),
                    "message": misconfig.get('Message'),
                    "resolution": misconfig.get('Resolution') # LLM에게 줄 핵심 정보
                })
    return findings

# --- Trivy 결과에서 쿼리 추출 ---
def extract_queries_from_trivy_results(trivy_json: dict) -> list[str]:
    """Trivy 스캔 결과(JSON)에서 RAG 검색에 사용할 쿼리들을 추출"""
    queries = []
    if not trivy_json or 'Results' not in trivy_json:
        return queries
    for result in trivy_json.get('Results', []):
        for misconfig in result.get('Misconfigurations', []):
            if title := misconfig.get('Title'):
                queries.append(title)
    return list(set(queries))

# --- 메인 분석 함수 ---
def get_trivy_and_rag_analysis(yaml_content: str):
    """
    YAML 내용을 입력받아 Trivy 스캔과 RAG 검색을 수행
    결과를 JSON 객체 또는 0(정상)으로 반환
    """
    if not os.path.exists(DB_PATH):
        return {"error": f"DB 경로를 찾을 수 없습니다: '{DB_PATH}'"}

    trivy_results = None
    temp_file_path = ''
    try:
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix=".yaml", encoding='utf-8') as temp_file:
            temp_file.write(yaml_content)
            temp_file_path = temp_file.name
        trivy_results = run_trivy_scan(temp_file_path)
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)

    if not trivy_results:
        return {"error": "Trivy 스캔에 실패했거나 결과가 없습니다."}

    security_queries = extract_queries_from_trivy_results(trivy_results)

    structured_findings = extract_structured_findings(trivy_results)

    
    # 취약점이 없으면 0 반환
    if not security_queries:
        return 0

    # --- 임베딩 모델과 Chroma DB 초기화 ---
    embedding_model = HuggingFaceEmbeddings(model_name=MODEL_NAME)
    print("[DEBUG] Chroma DB 초기화 직전")
    vector_db = Chroma(
        persist_directory=DB_PATH,
        embedding_function=embedding_model,
        collection_name=COLLECTION_NAME
    )
    print("[DEBUG] Chroma DB 초기화 완료")

    retriever = vector_db.as_retriever(search_kwargs={'k': 1})

    # --- 쿼리별 문서 검색 ---
    unique_docs_with_queries = {}
    for query in security_queries:
        retrieved_docs = retriever.get_relevant_documents(query)
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
    
    # --- 결과 정리 ---
    analysis_results_list = []
    for item in unique_docs_with_queries.values():
        doc = item['doc']
        sorted_queries = sorted(item['queries'])
        analysis_results_list.append({
            "retrieved_for_queries": sorted_queries,
            "source_document": {
                "content": doc.page_content,
                "metadata": doc.metadata
            }
        })
    
    analysis_results_list.sort(key=lambda x: x['source_document']['metadata'].get('id', ''))

    final_output = {
        "analyzed_yaml_content": yaml_content,
        "trivy_scan_summary": {
            "total_queries_generated": len(security_queries),
            "unique_documents_found": len(analysis_results_list)
        },
        "analysis_results": analysis_results_list,
        "structured_findings": structured_findings
    }

    return final_output

# --- 실행용 코드 ---
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용법: python3 db_handler.py <분석할_YAML_파일_경로>")
        sys.exit(1)

    yaml_file_path = sys.argv[1]

    if not os.path.exists(yaml_file_path):
        print(f"[오류] 파일을 찾을 수 없습니다: {yaml_file_path}")
        sys.exit(1)

    print("=" * 70)
    print(f"[시작] '{yaml_file_path}' 파일 분석 후 JSON 출력 테스트")
    print("=" * 70)

    try:
        with open(yaml_file_path, 'r', encoding='utf-8') as f:
            yaml_content_from_file = f.read()
    except Exception as e:
        print(f"[오류] 파일을 읽는 중 문제 발생: {e}")
        sys.exit(1)
    
    result = get_trivy_and_rag_analysis(yaml_content_from_file)

    if result == 0:
        print("\n" + "=" * 25, " [분석 결과: 정상] ", "=" * 26)
        print("Trivy 스캔 결과, 보안 문제점이 발견되지 않았습니다.")
        print("=" * 70)
    else:
        print("\n" + "=" * 28, " [최종 분석 결과] ", "=" * 28)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("\n" + "=" * 70)
        print("[종료] JSON 출력을 pipeline.py 등에서 활용 가능")
