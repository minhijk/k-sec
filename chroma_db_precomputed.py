# --- 1. 필요한 라이브러리 임포트 ---
import json
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# --- 데이터 로딩 함수들 ---
def load_texts_and_metadata(file_path: str) -> tuple[list[str], list[dict]]:
    """
    원본 JSON 파일에서 텍스트(page_content)와 메타데이터(metadata)를 로드합니다.
    """
    texts = []
    metadatas = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for item in data:
            if 'page_content' in item and 'metadata' in item:
                texts.append(item['page_content'])
                metadatas.append(item['metadata'])
            else:
                print(f"  [경고] 필수 키('page_content' 또는 'metadata')가 없는 항목을 건너뜁니다: {item}")
    except FileNotFoundError:
        print(f"[오류] 원본 문서 파일을 찾을 수 없습니다: {file_path}")
        print(" -> 'original_documents_file' 변수의 파일 경로를 확인해주세요.")
    except Exception as e:
        print(f"[오류] 원본 문서 파일 로드 중 에러 발생: {e}")
    return texts, metadatas

def load_vectors(file_path: str) -> list[list[float]]:
    """
    사전에 계산된 벡터가 저장된 JSON 파일을 로드합니다.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            vectors = json.load(f)
        return vectors
    except FileNotFoundError:
        print(f"[오류] 벡터 파일을 찾을 수 없습니다: {file_path}")
    except Exception as e:
        print(f"[오류] 벡터 파일 로드 중 에러 발생: {e}")
    return []

def main():
    # --- 파일 경로 설정 ---
    # 'vectors.json'을 만들기 위해 사용했던 원본 텍스트+메타데이터 파일을 지정합니다.
    original_documents_file = 'pre_vectors.json'
    precomputed_vectors_file = 'vectors.json'

    # --- 1. 데이터 준비 ---
    print("단계 1: 원본 문서(텍스트, 메타데이터)와 사전 계산된 벡터를 로드합니다.")
    texts, metadatas = load_texts_and_metadata(original_documents_file)
    vectors = load_vectors(precomputed_vectors_file)

    if not texts or not vectors:
        print("\n데이터 로드에 실패했습니다. 스크립트를 종료합니다.")
        return

    # --- 2. 데이터 무결성 검사 ---
    print("\n단계 2: 문서와 벡터의 개수가 일치하는지 확인합니다.")
    if len(texts) != len(vectors):
        print(f"[오류] 문서의 개수({len(texts)})와 벡터의 개수({len(vectors)})가 일치하지 않습니다.")
        print(" -> 동일한 데이터 소스로부터 생성된 파일들이 맞는지 확인해주세요.")
        return
    
    print(f"로드된 문서 개수: {len(texts)}")
    print(f"로드된 벡터 개수: {len(vectors)}")
    print(" -> 개수 일치 확인!")
    print("-" * 50)

    # --- 3. 임베딩 모델 준비 (검색용) ---
    # DB에 데이터를 '넣을 때'는 사전 계산된 벡터를 사용하므로 임베딩이 필요 없습니다.
    # 하지만, ChromaDB는 나중에 검색할 때를 대비해 어떤 임베딩 함수를 쓸지 알아야 하므로,
    # 데이터를 생성할 때 사용했던 것과 "동일한" 임베딩 모델을 지정해주어야 합니다.
    print("단계 3: 검색 쿼리를 임베딩할 모델을 로드합니다.")
    model_name = "jhgan/ko-sroberta-multitask"
    embeddings_model = HuggingFaceEmbeddings(model_name=model_name)
    print("모델 로드 완료:", model_name)
    print("-" * 50)
    
    # --- 4. ChromaDB 인스턴스 생성 및 데이터 추가 ---
    print("단계 4: 사전 계산된 벡터와 문서를 ChromaDB에 직접 추가합니다.")
    db_path = "./chroma_db_precomputed"
    
    # LangChain의 Chroma 클래스를 사용하여 텍스트와 벡터를 함께 추가합니다.
    # .from_embeddings를 사용하여 임베딩 과정 없이 바로 데이터를 저장합니다.
    Chroma.from_embeddings(
        texts=texts,
        embedding=embeddings_model, # 검색 시 쿼리 임베딩을 위해 필요
        embeddings=vectors,         # 여기에 사전 계산된 벡터를 전달
        metadatas=metadatas,
        collection_name="my_precomputed_db",
        persist_directory=db_path
    )
    
    print("\n벡터 데이터베이스 구축 및 저장 완료!")
    print(f"저장 위치: {db_path}")

if __name__ == "__main__":
    main()

