# --- 1. 필요한 라이브러리 임포트 ---
import yaml
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.vectorstores import VectorStoreRetriever

# --- 2. DB 정보 설정 (이전과 동일) ---
DB_PATH = "./chroma_db_precomputed"
COLLECTION_NAME = "my_precomputed_db"
MODEL_NAME = "jhgan/ko-sroberta-multitask"

# --- 3. 테스트용 YAML 데이터 (이전과 동일) ---
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
    YAML 내용에서 securityContext 등 보안과 직접 관련된 부분만 추출하여
    의미 있는 검색 쿼리 리스트를 생성합니다.
    """
    queries = []
    try:
        data = yaml.safe_load(yaml_content)
        
        # spec.containers 배열을 순회
        for container in data.get('spec', {}).get('containers', []):
            # 1. securityContext 내부의 모든 키-값 쌍을 쿼리로 생성
            if 'securityContext' in container and container['securityContext']:
                for key, value in container['securityContext'].items():
                    # "securityContext privileged: true" 와 같은 구체적인 쿼리 생성
                    queries.append(f"securityContext {key}: {value}")
            
            # 2. 'latest' 이미지 태그 사용 여부를 쿼리로 추가
            image = container.get('image', '')
            if ':' in image and image.endswith(':latest'):
                queries.append("image tag latest security risk")

            # 3. 리소스 limits 설정 누락 여부 관련 쿼리 추가 (예시)
            if 'resources' in container and 'limits' not in container['resources']:
                 queries.append("kubernetes resource limits not set")

    except yaml.YAMLError as e:
        print(f"❌ YAML 파싱 오류: {e}")
    
    return queries

def run_retriever_prototype():
    print("=" * 70)
    print("🛰️  [개선版] 보안 중심 RAG 검색기 프로토타입을 시작합니다.")
    print("=" * 70)

    try:
        # --- 단계 1: YAML에서 '보안 관련' 쿼리만 선별적으로 추출 ---
        print("\n[단계 1] YAML 파일에서 '보안 관련' 검색 쿼리를 선별적으로 추출합니다...")
        security_queries = extract_security_queries_from_yaml(SAMPLE_INSECURE_YAML)
        
        if not security_queries:
            print(" -> 보안 관련 검색 쿼리를 찾지 못했습니다.")
            return
            
        print(f" -> 총 {len(security_queries)}개의 보안 관련 검색 쿼리를 생성했습니다. ✅")
        for i, q in enumerate(security_queries, 1):
            print(f"   쿼리 {i}: \"{q}\"")
        print("-" * 70)

        # --- 단계 2: DB 연결 및 검색기 생성 ---
        print("\n[단계 2] DB 연결 및 검색기를 생성합니다...")
        embedding_model = HuggingFaceEmbeddings(model_name=MODEL_NAME)
        vector_db = Chroma(persist_directory=DB_PATH, embedding_function=embedding_model, collection_name=COLLECTION_NAME)
        retriever = VectorStoreRetriever(vectorstore=vector_db, search_kwargs={'k': 2}) # 각 쿼리당 2개씩 검색
        print(" -> DB 연결 및 검색기 생성 완료! ✅")

        # --- 단계 3: 개별 쿼리 검색 및 결과 통합 (중복 제거) ---
        print(f"\n[단계 3] {len(security_queries)}개의 쿼리에 대해 순차적으로 검색을 수행하고 결과를 통합합니다...")
        
        unique_results = {} # 중복 제거를 위한 딕셔너리 {문서내용: 문서객체}
        for i, query in enumerate(security_queries, 1):
            print(f" 🔍 {i}/{len(security_queries)} 번째 쿼리 검색 중: \"{query}\"")
            retrieved_docs = retriever.invoke(query)
            for doc in retrieved_docs:
                if doc.page_content not in unique_results:
                    unique_results[doc.page_content] = doc

        final_docs = list(unique_results.values())

        print("\n" + "=" * 25, " [최종 검색 결과 (중복 제거)] ", "=" * 25)
        if not final_docs:
            print("\n -> 텅.. 검색된 문서가 없습니다.")
        
        for i, doc in enumerate(final_docs, 1):
            print(f"\n--- [결과 {i}] ---")
            source = doc.metadata.get('source', 'N/A')
            page = doc.metadata.get('page', 'N/A')
            print(f"📂 출처: {source} (페이지: {page})")
            print("\n📜 내용:")
            print(doc.page_content)
        
        print("\n" + "=" * 70)

    except Exception as e:
        print(f"\n❌ [오류] 프로토타입 실행 중 문제가 발생했습니다: {e}")

if __name__ == "__main__":
    run_retriever_prototype()