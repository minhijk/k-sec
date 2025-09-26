# --- 1. 라이브러리 불러오기 ---
import yaml
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.vectorstores import VectorStoreRetriever

# --- 2. DB 설정 ---
DB_PATH = "./chroma_db_precomputed"
COLLECTION_NAME = "my_precomputed_db"
MODEL_NAME = "jhgan/ko-sroberta-multitask"

# --- 3. 테스트용 YAML 데이터 ---
SAMPLE_INSECURE_YAML = """
apiVersion: v1
kind: Pod
metadata:
  name: vulnerable-pod-example
spec:
  containers:
  - name: insecure-container
    image: nginx:latest
    securityContext:
      privileged: true
      runAsUser: 0
    ports:
    - containerPort: 80
    resources:
      requests:
        memory: "64Mi"
        cpu: "100m"
"""

def extract_security_queries_from_yaml(yaml_content: str) -> list[str]:
    """
    YAML에서 보안 관련 부분만 뽑아 쿼리 리스트로 생성
    """
    queries = []
    try:
        data = yaml.safe_load(yaml_content)
        
        # containers 반복
        for container in data.get('spec', {}).get('containers', []):
            # securityContext 내부 키-값 쿼리로 생성
            if 'securityContext' in container and container['securityContext']:
                for key, value in container['securityContext'].items():
                    queries.append(f"securityContext {key}: {value}")
            
            # latest 이미지 태그 사용 여부
            image = container.get('image', '')
            if ':' in image and image.endswith(':latest'):
                queries.append("image tag latest security risk")

            # 리소스 limits 설정 누락 여부
            if 'resources' in container and 'limits' not in container['resources']:
                 queries.append("kubernetes resource limits not set")

    except yaml.YAMLError as e:
        print(f"YAML 파싱 오류: {e}")
    
    return queries

def run_retriever_prototype():
    print("=" * 70)
    print("[시작] 보안 중심 RAG 검색기 프로토타입")
    print("=" * 70)

    try:
        # --- 1단계: YAML에서 보안 관련 쿼리 추출 ---
        print("\n[1단계] YAML에서 보안 관련 쿼리 추출")
        security_queries = extract_security_queries_from_yaml(SAMPLE_INSECURE_YAML)
        
        if not security_queries:
            print(" -> 보안 관련 쿼리 없음")
            return
            
        print(f" -> 총 {len(security_queries)}개 쿼리 생성")
        for i, q in enumerate(security_queries, 1):
            print(f"   쿼리 {i}: \"{q}\"")
        print("-" * 70)

        # --- 2단계: DB 연결 및 검색기 생성 ---
        print("\n[2단계] DB 연결 및 검색기 생성")
        embedding_model = HuggingFaceEmbeddings(model_name=MODEL_NAME)
        vector_db = Chroma(persist_directory=DB_PATH, embedding_function=embedding_model, collection_name=COLLECTION_NAME)
        retriever = VectorStoreRetriever(vectorstore=vector_db, search_kwargs={'k': 2}) # 각 쿼리당 2개 검색
        print(" -> 완료")

        # --- 3단계: 쿼리 검색 및 결과 통합 ---
        print(f"\n[3단계] {len(security_queries)}개 쿼리 검색 후 결과 통합")
        
        unique_results = {} # 중복 제거
        for i, query in enumerate(security_queries, 1):
            print(f" {i}/{len(security_queries)}번째 쿼리: \"{query}\"")
            retrieved_docs = retriever.invoke(query)
            for doc in retrieved_docs:
                if doc.page_content not in unique_results:
                    unique_results[doc.page_content] = doc

        final_docs = list(unique_results.values())

        print("\n" + "=" * 25, " [최종 결과] ", "=" * 25)
        if not final_docs:
            print("\n -> 검색 결과 없음")
        
        for i, doc in enumerate(final_docs, 1):
            print(f"\n--- [결과 {i}] ---")
            source = doc.metadata.get('source', 'N/A')
            page = doc.metadata.get('page', 'N/A')
            print(f"출처: {source} (페이지: {page})")
            print("\n내용:")
            print(doc.page_content)
        
        print("\n" + "=" * 70)

    except Exception as e:
        print(f"\n[오류] 실행 중 문제 발생: {e}")

if __name__ == "__main__":
    run_retriever_prototype()
