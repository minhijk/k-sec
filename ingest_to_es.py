# ingest_to_es.py - Elasticsearch에 데이터 색인 스크립트

import json
from langchain_core.documents import Document
from langchain_elasticsearch import ElasticsearchStore
from langchain_huggingface import HuggingFaceEmbeddings
import os
# elasticsearch 클라이언트를 직접 사용하기 위해 임포트
from elasticsearch import Elasticsearch

# --- 설정 변수 ---
# ... (기존과 동일) ...
ELASTIC_URL = "http://localhost:9200"
INDEX_NAME = "k8s_security_documents"
MODEL_NAME = "jhgan/ko-sroberta-multitask"
SOURCE_JSON_PATH = "structured_all.json" 

def ingest_data_to_es():
    # ... (1, 2, 3번 과정은 기존과 동일) ...
    # 1. 임베딩 모델 로드
    print("🚀 1. 임베딩 모델을 로드합니다...")
    try:
        embedding_model = HuggingFaceEmbeddings(model_name=MODEL_NAME)
        print("✅ 임베딩 모델 로드 완료.")
    except Exception as e:
        print(f"❌ 임베딩 모델 로드 실패: {e}")
        return

    # 2. 소스 JSON 파일 로드
    if not os.path.exists(SOURCE_JSON_PATH):
        print(f"❌ 파일 없음: '{SOURCE_JSON_PATH}' 파일을 찾을 수 없습니다. 경로를 확인해주세요.")
        return
    print(f"📄 2. '{SOURCE_JSON_PATH}' 파일에서 데이터를 로드합니다...")
    with open(SOURCE_JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 3. LangChain Document 객체로 변환
    documents = []
    for item in data:
        page_content = f"Title: {item.get('title', '')}\nDescription: {item.get('content_description', '')}\nRemediation: {item.get('content_remediation', '')}"
        metadata = {
            "id": item.get("id"), "source": item.get("source"),
            "category_l1": item.get("category_l1"), "category_l2": item.get("category_l2"),
            "title": item.get("title")
        }
        documents.append(Document(page_content=page_content, metadata=metadata))
    print(f"✅ {len(documents)}개의 문서를 LangChain Document 형식으로 변환했습니다.")

    # ------------------ (여기가 수정/추가된 부분) ------------------
    # 4. Elasticsearch 클라이언트 생성 및 기존 인덱스 삭제
    print(f"🔍 4. 기존 '{INDEX_NAME}' 인덱스가 있는지 확인합니다...")
    try:
        es_client = Elasticsearch(ELASTIC_URL)
        if es_client.indices.exists(index=INDEX_NAME):
            print(f"🗑️ 기존 '{INDEX_NAME}' 인덱스를 삭제합니다.")
            es_client.indices.delete(index=INDEX_NAME)
            print(f"✅ 기존 인덱스 삭제 완료.")
    except Exception as e:
        print(f"\n❌ Elasticsearch 연결 또는 인덱스 삭제 중 오류 발생: {e}")
        print("   Docker로 Elasticsearch 서버가 실행 중인지 확인해주세요.")
        return
    # -----------------------------------------------------------------
    
    # 5. Elasticsearch에 데이터 색인 (Ingest) - (기존 4번 과정)
    print(f"🚚 5. Elasticsearch에 데이터 색인을 새로 시작합니다...")
    try:
        db = ElasticsearchStore.from_documents(
            documents,
            embedding_model,
            es_url=ELASTIC_URL,
            index_name=INDEX_NAME,
            strategy=ElasticsearchStore.ApproxRetrievalStrategy()
        )
        if not db.client.indices.exists(index=INDEX_NAME):
            raise Exception("인덱스 생성에 실패했습니다.")
        print(f"\n🎉 성공! '{INDEX_NAME}' 인덱스에 {len(documents)}개의 문서가 성공적으로 색인되었습니다.")
    except Exception as e:
        print(f"\n❌ Elasticsearch 색인 중 오류 발생: {e}")

if __name__ == "__main__":
    ingest_data_to_es()