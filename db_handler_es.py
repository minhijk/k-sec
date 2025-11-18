# db_handler_es.py (최적화 버전: Trivy=RAG / KICS=Direct)

import yaml
import subprocess
import json
import os
import sys
import uuid
import time
import gc
import shutil
import tempfile
from langchain.retrievers import EnsembleRetriever
from langchain_elasticsearch import ElasticsearchStore, ElasticsearchRetriever
from langchain_huggingface import HuggingFaceEmbeddings

# --- 설정 변수 ---
ELASTIC_URL = os.getenv("ELASTIC_URL", "http://localhost:9200")
INDEX_NAME = os.getenv("INDEX_NAME", "k8s_security_documents")
MODEL_NAME = os.getenv("MODEL_NAME", "jhgan/ko-sroberta-multitask")

# --- 전역 객체 ---
EMBEDDING_MODEL = None
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
        except Exception:
            pass
    
    if ENSEMBLE_RETRIEVER:
        ENSEMBLE_RETRIEVER = None
    
    gc.collect()

def initialize_elasticsearch():
    """Elasticsearch 연결을 초기화합니다 (Trivy 스캔 시에만 필요)"""
    global VECTOR_STORE, ENSEMBLE_RETRIEVER, EMBEDDING_MODEL
    
    #os.environ["HUGGING_FACE_HUB_TOKEN"] = "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"

    if ENSEMBLE_RETRIEVER is not None:
        return True
    
    try:
        # 임베딩 모델 지연 로딩 (메모리 절약)
        if EMBEDDING_MODEL is None:
            print(f"[INIT] 임베딩 모델 로드 중... ({MODEL_NAME})")
            EMBEDDING_MODEL = HuggingFaceEmbeddings(
                model_name=MODEL_NAME,
                model_kwargs={'device': 'cpu'},
                encode_kwargs={'normalize_embeddings': True}
            )

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


def run_trivy_scan(yaml_content: str) -> dict:
    """Trivy 스캔 (메모리 효율을 위해 stdin 우선 사용)"""
    start_time = time.time()
    command = ['trivy', 'config', '--format', 'json', '-']
    
    try:
        # print(f"[TRIVY] 스캔 시작...") # 로그 너무 많으면 주석 처리
        result = subprocess.run(
            command, input=yaml_content, capture_output=True,
            text=True, check=True, encoding='utf-8', timeout=15
        )
        return json.loads(result.stdout)
    except Exception:
        # 실패 시 파일 기반 재시도
        temp_file = f"temp_trivy_{uuid.uuid4()}.yaml"
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(yaml_content)
            command = ['trivy', 'config', '--format', 'json', temp_file]
            result = subprocess.run(
                command, capture_output=True, text=True, 
                check=True, encoding='utf-8', timeout=15
            )
            return json.loads(result.stdout)
        except Exception as e:
            print(f"[TRIVY] ❌ 스캔 실패: {e}")
            return None
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)


def extract_queries_from_trivy_results(trivy_json: dict) -> list[str]:
    """Trivy 결과에서 검색 쿼리 추출"""
    queries = []
    if not trivy_json or 'Results' not in trivy_json: 
        return queries
    
    for result in trivy_json.get('Results', []):
        for misconfig in result.get('Misconfigurations', []):
            title = misconfig.get('Title', '')
            misconfig_id = misconfig.get('ID', '')
            description = misconfig.get('Description', '')
            resolution = misconfig.get('Resolution', '')
            queries.append(f"{misconfig_id}: {title}. {description}. {resolution}")
            
    return list(set(queries))

def run_kics_scan(yaml_content: str) -> dict:
    """KICS 스캔 (CWD, 명령어, 경로 문제 모두 수정한 최종본)"""
    
    # ==================================================================
    # [설정] KICS 실행 파일('kics.exe')의 "절대 경로"
    # 예: r"C:\kics\bin\kics.exe"
    KICS_EXECUTABLE_PATH = r"C:\\Users\\user\\Desktop\\kics\\kics\\bin\\kics.exe" 
    # ==================================================================

    if not os.path.exists(KICS_EXECUTABLE_PATH):
        print(f"[ERROR] KICS 실행 파일을 찾을 수 없습니다: {KICS_EXECUTABLE_PATH}")
        return None

    # [!!! 개선 1: CWD 설정 !!!]
    # 'kics.exe'의 부모 폴더(bin)의 부모 폴더(kics)를 CWD로 설정
    # (PS C:\...> .\bin\kics.exe 와 동일한 효과)
    kics_base_dir = os.path.dirname(os.path.dirname(KICS_EXECUTABLE_PATH))
    print(f"[DEBUG] KICS CWD 설정: {kics_base_dir}")

    # --- 경로 로직 ---
    base_temp_dir = tempfile.gettempdir() 
    temp_dir = os.path.join(base_temp_dir, f"temp_kics_{uuid.uuid4()}")
    os.makedirs(temp_dir, exist_ok=True)
    
    temp_file_name = os.path.join(temp_dir, "target.yaml")
    output_name = "kics_result" # KICS가 생성할 파일 이름 (확장자 제외)
    temp_result_dir = os.path.join(temp_dir, "results") # KICS가 결과를 저장할 "폴더"
    os.makedirs(temp_result_dir, exist_ok=True)
    
    # 스크립트가 최종적으로 읽어야 할 "파일"의 절대 경로
    result_file_path = os.path.join(temp_result_dir, f"{output_name}.json") 

    print(f"[DEBUG] 임시 폴더: {temp_dir}")
    print(f"[DEBUG] 스캔 대상 파일: {temp_file_name}")
    print(f"[DEBUG] KICS 출력 폴더: {temp_result_dir}")
    print(f"[DEBUG] 최종 결과 파일: {result_file_path}")
    # ---------------------------

    try:
        with open(temp_file_name, 'w', encoding='utf-8') as f:
            f.write(yaml_content)
            
        # [!!! 개선 2: 명령어 수정 !!!]
        # -o 에는 "폴더" 경로(temp_result_dir)를 지정합니다.
        # --output-name 에 "파일" 이름(output_name)을 지정합니다.
        command = [
            KICS_EXECUTABLE_PATH,
            'scan',
            '-p', temp_file_name,       # 스캔할 파일 (절대 경로)
            '-o', temp_result_dir,      # 결과를 저장할 "폴더" (절대 경로)
            '--output-name', output_name, # 결과 "파일 이름" (확장자 제외)
            '--report-formats', 'json',
        ]
        
        print(f"[DEBUG] 실행 명령어: {' '.join(command)}")
        
        result = subprocess.run(
            command, 
            capture_output=True, text=True, 
            check=False, encoding='utf-8', timeout=60,
            cwd=kics_base_dir  # [!!!] CWD(현재 작업 디렉터리)를 KICS 홈으로 변경
        )
        
        print(f"[DEBUG] KICS 종료 코드: {result.returncode}")
        if result.stderr:
            print(f"[DEBUG] STDERR (에러 로그):\n{result.stderr}")
        if result.stdout:
            print(f"[DEBUG] STDOUT (실행 로그):\n{result.stdout[:500]}...") 

        print(f"[DEBUG] 결과 파일 찾는 중: {result_file_path}")
        
        if os.path.exists(result_file_path) and os.path.isfile(result_file_path): # [개선] 파일인지도 확인
            print("[DEBUG] ✅ 결과 파일 발견! 내용을 읽습니다.")
            time.sleep(0.1) # 파일 I/O 경쟁을 피하기 위한 짧은 대기
            with open(result_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            print("[DEBUG] ❌ 결과 파일이 생성되지 않았습니다. (파일이 아니거나 존재하지 않음)")
            if os.path.isdir(result_file_path):
                 print(f"[DEBUG] ❌ FATAL: '{result_file_path}'가 파일이 아닌 디렉터리로 생성되었습니다.")
            return None

    except Exception as e:
        print(f"[KICS] ❌ 실행 중 치명적 오류 발생: {e}")
        return None
        
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            # print(f"[DEBUG] 임시 폴더 삭제 완료: {temp_dir}")

def parse_kics_results_to_text(kics_json: dict) -> str:
    """
    KICS 결과를 LLM이 바로 읽을 수 있는 텍스트 형식으로 변환합니다.
    (논리 오류 수정: 0건 탐지 시 "" 반환)
    """
    if not kics_json or 'queries' not in kics_json:
        return ""

    # [!!! 개선 3: KICS 0건 처리 !!!]
    query_list = kics_json.get('queries', [])
    if not query_list:
        print("[DEBUG] KICS 스캔 0건 (정상)")
        return "" # 0건 탐지 시 빈 문자열 반환
        
    report_text = "### KICS 보안 스캔 결과 (2차 검증)\n"
    report_text += "다음은 정적 분석 도구 KICS가 발견한 보안 취약점 목록입니다:\n\n"
    
    for idx, query in enumerate(query_list, 1):
        name = query.get('query_name', 'Unknown Issue')
        severity = query.get('severity', 'INFO')
        description = query.get('description', '')
        platform = query.get('platform', 'Kubernetes')
        
        files_info = query.get('files', [])
        location_str = ""
        if files_info:
            line = files_info[0].get('line', '?')
            location_str = f"(Line: {line})"

        report_text += f"{idx}. [{severity}] {name} {location_str}\n"
        report_text += f"   - 설명: {description}\n"
        report_text += f"   - 플랫폼: {platform}\n\n"
        
    return report_text


def get_trivy_and_rag_analysis(yaml_content: str):
    """
    1. Trivy 스캔 -> 결과 있으면 -> RAG 검색 (Deep Analysis)
    2. Trivy 0건 -> KICS 스캔 -> 결과 있으면 -> 텍스트 변환 후 리턴 (Fast Analysis)
    (논리 오류 수정: KICS 스캔 실패 감지)
    """
    total_start = time.time()
    print("\n" + "="*70)
    print("[ANALYSIS] 보안 분석 시작...")

    # --- [Step 1] Trivy 스캔 ---
    trivy_results = run_trivy_scan(yaml_content)
    trivy_queries = extract_queries_from_trivy_results(trivy_results)

    if trivy_queries:
        # (Trivy 로직 ... 생략)
        print(f"[STEP 1] Trivy: {len(trivy_queries)}개의 이슈 발견. RAG 검색을 시작합니다.")
        
        if not initialize_elasticsearch():
            return {"error": "Elasticsearch 연결 실패"}
            
        rag_results = []
        unique_docs = set()
        
        for q in trivy_queries:
            try:
                docs = ENSEMBLE_RETRIEVER.invoke(q)
                if docs:
                    doc = docs[0]
                    rag_results.append({
                        "query": q,
                        "doc_content": doc.page_content,
                        "metadata": doc.metadata
                    })
                    unique_docs.add(doc.page_content)
            except Exception:
                continue
                
        return {
            "status": "TRIVY_DETECTED",
            "summary": f"Trivy 발견 ({len(trivy_queries)}건), RAG 문서 ({len(unique_docs)}건)",
            "data": rag_results
        }

    # --- [Step 2] Trivy 결과 없음 -> KICS 스캔 ---
    print("[STEP 1] Trivy 결과 없음 (0건). KICS 2차 스캔을 시도합니다.")
    kics_results = run_kics_scan(yaml_content)
    
    # [!!! 개선 3: KICS '실패' 처리 !!!]
    # run_kics_scan이 None을 반환하면(스캔 실패) KICS_ERROR로 즉시 반환
    if kics_results is None:
        print("[STEP 2] ❌ KICS 스캔 실행 실패. (로그 확인 필요)")
        return {
            "status": "KICS_ERROR",
            "summary": "KICS 스캔 실행 중 오류 발생",
            "data": "KICS 스캔 프로세스가 실패했습니다. (timeout, command not found, or file I/O error)"
        }

    # KICS 결과 파싱 (텍스트 변환)
    # (개선 3: 0건이면 ""가 반환됨)
    kics_text_report = parse_kics_results_to_text(kics_results)
    
    if kics_text_report: 
        print("[STEP 2] KICS: 보안 이슈 발견. RAG 없이 직접 결과를 반환합니다.")
        return {
            "status": "KICS_DETECTED",
            "summary": "KICS 발견 (RAG 미사용)",
            "data": kics_text_report
        }
    
    # --- [Step 3] 둘 다 없음 ---
    print("[RESULT] Trivy와 KICS 모두 보안 이슈를 발견하지 못했습니다.")
    return 0

def shutdown_handler():
    cleanup_resources()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(1)
    
    yaml_file_path = sys.argv[1]
    if os.path.exists(yaml_file_path):
        with open(yaml_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        final_result = get_trivy_and_rag_analysis(content)
        
        # 결과 출력 (디버깅 및 연동용)
        print(json.dumps(final_result, ensure_ascii=False, indent=2))
    
    shutdown_handler()