import yaml
import subprocess
import json
import tempfile
import os
import sys  # <<< 추가된 부분 (1/2) >>>
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# --- 설정 변수 ---
DB_PATH = "./chroma_db_precomputed"
COLLECTION_NAME = "my_precomputed_db"
MODEL_NAME = "jhgan/ko-sroberta-multitask"

def run_trivy_scan(file_path: str) -> dict:
    """Trivy를 실행하여 YAML 설정 파일의 취약점을 스캔하고 결과를 JSON으로 반환합니다."""
    command = ['trivy', 'config', '--format', 'json', file_path]
    try:
        print(f" -> Trivy 스캔 실행: {' '.join(command)}")
        result = subprocess.run(
            command, capture_output=True, text=True, check=True, encoding='utf-8'
        )
        return json.loads(result.stdout)
    except FileNotFoundError:
        print("\n[오류] 'trivy' 명령어를 찾을 수 없습니다. Trivy가 설치되어 있고 PATH에 등록되어 있는지 확인하세요.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"\n[오류] Trivy 스캔 중 오류가 발생했습니다: {e.stderr}")
        return None
    except json.JSONDecodeError:
        print("\n[오류] Trivy 출력 결과를 JSON으로 파싱하는 데 실패했습니다.")
        return None

def extract_queries_from_trivy_results(trivy_json: dict) -> list[str]:
    """Trivy 스캔 결과(JSON)에서 RAG 검색에 사용할 쿼리들을 추출합니다."""
    queries = []
    if not trivy_json or 'Results' not in trivy_json:
        return queries
    for result in trivy_json.get('Results', []):
        for misconfig in result.get('Misconfigurations', []):
            if title := misconfig.get('Title'):
                queries.append(title)
    return list(set(queries))

def get_trivy_and_rag_analysis(yaml_content: str) -> dict:
    """
    YAML 내용을 입력받아 Trivy 스캔과 RAG 검색을 수행하고,
    그 결과를 정렬하여 구조화된 딕셔너리(JSON 변환용)로 반환하는 메인 함수.
    이 함수가 pipeline.py에서 호출할 최종 결과물입니다.
    """
    if not os.path.exists(DB_PATH):
        return {"error": f"DB 경로를 찾을 수 없습니다: '{DB_PATH}'"}

    trivy_results = None
    try:
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix=".yaml", encoding='utf-8') as temp_file:
            temp_file.write(yaml_content)
            temp_file_path = temp_file.name
        trivy_results = run_trivy_scan(temp_file_path)
    finally:
        if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
            os.remove(temp_file_path)

    if not trivy_results:
        return {"error": "Trivy 스캔에 실패했거나 결과가 없습니다."}

    security_queries = extract_queries_from_trivy_results(trivy_results)
    if not security_queries:
        return {"error": "Trivy가 보안 문제점을 발견하지 못했습니다."}

    embedding_model = HuggingFaceEmbeddings(model_name=MODEL_NAME)
    vector_db = Chroma(persist_directory=DB_PATH, embedding_function=embedding_model, collection_name=COLLECTION_NAME)
    retriever = vector_db.as_retriever(search_kwargs={'k': 1})

    unique_docs_with_queries = {}
    for query in security_queries:
        retrieved_docs = retriever.invoke(query)
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
        "analysis_results": analysis_results_list
    }

    return final_output

# --- 이 파일을 직접 실행할 때를 위한 테스트 코드 ---
if __name__ == "__main__":
    # <<< 수정된 부분 (2/2) >>>
    # 커맨드 라인에서 파일 경로를 인자로 받도록 수정
    
    # 1. 인자가 제대로 주어졌는지 확인
    if len(sys.argv) != 2:
        print("사용법: python3 db_handler.py <분석할_YAML_파일_경로>")
        # 스크립트 이름(sys.argv[0])과 파일 경로(sys.argv[1]), 총 2개여야 함
        sys.exit(1) # 오류 코드 1과 함께 종료

    # 2. 파일 경로를 변수에 저장
    yaml_file_path = sys.argv[1]

    # 3. 파일이 실제로 존재하는지 확인
    if not os.path.exists(yaml_file_path):
        print(f"[오류] 파일을 찾을 수 없습니다: {yaml_file_path}")
        sys.exit(1)

    print("=" * 70)
    print(f"[시작] '{yaml_file_path}' 파일 분석 후 JSON 출력 테스트")
    print("=" * 70)

    # 4. 파일을 읽어서 내용을 변수에 저장
    try:
        with open(yaml_file_path, 'r', encoding='utf-8') as f:
            yaml_content_from_file = f.read()
    except Exception as e:
        print(f"[오류] 파일을 읽는 중 문제가 발생했습니다: {e}")
        sys.exit(1)

    # 5. 파일 내용을 인자로 하여 핵심 분석 함수 호출
    results_dict = get_trivy_and_rag_analysis(yaml_content_from_file)

    # 6. 반환된 딕셔너리를 JSON으로 변환하여 출력
    json_output = json.dumps(results_dict, indent=2, ensure_ascii=False)
    
    print("\n" + "=" * 28, " [최종 생성된 JSON] ", "=" * 28)
    print(json_output)
    print("\n" + "=" * 70)
    print("[종료] 이 JSON 출력을 pipeline.py로 전달하면 됩니다.")