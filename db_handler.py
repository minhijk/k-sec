import yaml
import subprocess
import json
import tempfile
import os
import textwrap
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.vectorstores import VectorStoreRetriever

DB_PATH = "./chroma_db_precomputed"
COLLECTION_NAME = "my_precomputed_db"
MODEL_NAME = "jhgan/ko-sroberta-multitask"

# <<< 수정됨 >>>: 현실적인 취약점을 포함한 YAML로 교체
SAMPLE_INSECURE_YAML = """
# --- 취약한 웹 애플리케이션 배포 예제 ---
# 이 YAML은 일반적인 보안 설정 오류를 다수 포함하고 있습니다.
apiVersion: apps/v1
kind: Deployment
metadata:
  name: insecure-webapp-deployment
  labels:
    app: insecure-webapp
spec:
  replicas: 1
  selector:
    matchLabels:
      app: insecure-webapp
  template:
    metadata:
      labels:
        app: insecure-webapp
    spec:
      containers:
      - name: web-server-container
        # 문제점 1: 알려진 취약점이 있는 오래된 버전의 이미지 및 'latest' 태그 사용
        image: nginx:1.18-alpine 
        
        ports:
        - containerPort: 80

        # 문제점 2: 리소스 요청만 있고 상한(limit)이 없어 DoS 공격에 취약
        resources:
          requests:
            memory: "128Mi"
            cpu: "250m"
        
        # 문제점 3: 중요 정보(비밀)를 환경 변수에 하드코딩
        env:
        - name: API_KEY
          value: "abc123-very-secret-key-do-not-use"
        - name: DATABASE_URL
          value: "prod-db-host:5432"

        # 문제점 4: 컨테이너에 과도한 권한 부여 (가장 심각한 설정 오류들)
        securityContext:
          runAsUser: 0 # root 유저로 실행
          privileged: false # privileged는 피했지만...
          allowPrivilegeEscalation: true # 권한 상승 허용
          readOnlyRootFilesystem: false # 루트 파일 시스템을 쓰기 가능 상태로 둠
          capabilities:
            add:
            - "NET_ADMIN" # 불필요하고 위험한 커널 기능 추가

        # 문제점 5: 민감한 호스트의 디렉터리를 컨테이너 내부에 마운트 (컨테이너 탈출 경로)
        volumeMounts:
        - name: host-etc
          mountPath: /host/etc
          readOnly: true # 읽기 전용이라도 호스트의 설정 정보 유출에 매우 위험
      
      volumes:
      - name: host-etc
        hostPath:
          path: /etc # 호스트의 /etc 디렉터리

---
# --- 외부 노출을 위한 서비스 ---
apiVersion: v1
kind: Service
metadata:
  name: insecure-webapp-service
spec:
  # 문제점 6: 내부용 서비스일 수 있는데 외부 IP로 접근 가능한 NodePort 사용
  type: NodePort 
  selector:
    app: insecure-webapp
  ports:
  - protocol: TCP
    port: 80
    targetPort: 80
    nodePort: 30080 # 고정된 포트를 외부에 노출
"""

def run_trivy_scan(file_path: str) -> dict:
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
    queries = []
    if not trivy_json or 'Results' not in trivy_json or not trivy_json['Results']:
        return queries

    for result in trivy_json.get('Results', []):
        for misconfig in result.get('Misconfigurations', []):
            title = misconfig.get('Title')
            if title:
                queries.append(title)
                
    return list(set(queries))

def run_trivy_based_retriever():
    print("=" * 70)
    print("[시작] Trivy 연동 보안 RAG 검색기")
    print("=" * 70)

    if not os.path.exists(DB_PATH):
        print(f"\n[오류] DB 경로를 찾을 수 없습니다: '{DB_PATH}'")
        print(" -> 먼저 DB 구축 스크립트를 실행하여 벡터 DB를 생성해주세요.")
        return

    try:
        print("\n[1-2단계] Trivy 스캔 및 DB 검색용 쿼리 추출")
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix=".yaml", encoding='utf-8') as temp_file:
            temp_file.write(SAMPLE_INSECURE_YAML)
            temp_file_path = temp_file.name
        
        trivy_results = run_trivy_scan(temp_file_path)
        os.remove(temp_file_path)

        if not trivy_results:
            print(" -> Trivy 스캔에 실패했거나 결과가 없습니다."); return

        security_queries = extract_queries_from_trivy_results(trivy_results)
        
        if not security_queries:
            print(" -> Trivy가 보안 문제점을 발견하지 못했습니다."); return
            
        print(f" -> 총 {len(security_queries)}개의 고유한 보안 관련 쿼리 생성 완료")
        
        print("\n[3단계] DB 연결 및 검색기 생성")
        embedding_model = HuggingFaceEmbeddings(model_name=MODEL_NAME)
        vector_db = Chroma(persist_directory=DB_PATH, embedding_function=embedding_model, collection_name=COLLECTION_NAME)
        retriever = VectorStoreRetriever(vectorstore=vector_db, search_kwargs={'k': 1})
        print(f" -> DB '{DB_PATH}' 에서 검색기 생성 완료 (k=1)")

        print(f"\n[4단계] {len(security_queries)}개 쿼리로 DB 검색 및 결과 통합")
        
        unique_docs_with_queries = {} 
        
        for i, query in enumerate(security_queries, 1):
            print(f" -> {i}/{len(security_queries)}번째 쿼리 검색: \"{query}\"")
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
        
        print("\n" + "=" * 28, " [최종 검색 결과] ", "=" * 28)
        
        final_results = list(unique_docs_with_queries.values())
        if not final_results:
            print("\n -> 모든 쿼리에 대해 검색된 결과가 없습니다.")
        
        for i, result_item in enumerate(final_results, 1):
            doc = result_item['doc']
            queries = result_item['queries']
            
            print(f"\n--- [결과 {i}] ---")
            
            print("🔍 검색된 쿼리 목록:")
            for q in queries:
                print(f"  - \"{q}\"")
            print("-" * 25)

            metadata_parts = []
            if doc.metadata and 'source' in doc.metadata:
                metadata_parts.append(f"출처: {doc.metadata['source']}")
            if doc.metadata and 'page' in doc.metadata:
                 metadata_parts.append(f"페이지: {doc.metadata['page']}")
            
            if metadata_parts:
                print(f"📄 관련 정보: {', '.join(metadata_parts)}")

            print("\n📝 문서 내용:")
            wrapped_content = textwrap.fill(
                doc.page_content,
                width=90,
                initial_indent="  ",
                subsequent_indent="  "
            )
            print(wrapped_content)

        print("\n" + "=" * 70)
        print("[종료] 모든 과정이 완료되었습니다.")

    except Exception as e:
        print(f"\n[치명적 오류] 실행 중 예기치 못한 문제가 발생했습니다: {e}")

if __name__ == "__main__":
    run_trivy_based_retriever()