import json
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# --- 데이터 로딩 함수들 ---
def load_texts_and_metadata(file_path: str) -> tuple[list[str], list[dict]]:
    texts = []
    metadatas = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for item in data:
            if 'page_content' in item and 'metadata' in item:
                texts.append(item['page_content'])
                metadata = item['metadata'].copy()
                
                # references가 리스트면 문자열로 변환
                if 'references' in metadata and isinstance(metadata['references'], list):
                    metadata['references'] = ", ".join(metadata['references'])
                
                metadatas.append(metadata)
            else:
                print(f"  [경고] 필수 키('page_content' 또는 'metadata')가 없는 항목을 건너뜁니다: {item}")
    except FileNotFoundError:
        print(f"[오류] 원본 문서 파일을 찾을 수 없습니다: {file_path}")
    except Exception as e:
        print(f"[오류] 원본 문서 파일 로드 중 에러 발생: {e}")
    return texts, metadatas

def load_vectors(file_path: str) -> list[list[float]]:
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
    original_documents_file = 'vector/pre_vectors.json'
    precomputed_vectors_file = 'vector/vectors.json'

    print("단계 1: 원본 문서(텍스트, 메타데이터)와 사전 계산된 벡터를 로드합니다.")
    texts, metadatas = load_texts_and_metadata(original_documents_file)
    vectors = load_vectors(precomputed_vectors_file)

    if not texts or not vectors:
        print("\n데이터 로드에 실패했습니다. 스크립트를 종료합니다.")
        return

    print("\n단계 2: 문서와 벡터의 개수가 일치하는지 확인합니다.")
    if len(texts) != len(vectors):
        print(f"[오류] 문서의 개수({len(texts)})와 벡터의 개수({len(vectors)})가 일치하지 않습니다.")
        return
    
    print(f"로드된 문서 개수: {len(texts)}")
    print(f"로드된 벡터 개수: {len(vectors)}")
    print(" -> 개수 일치 확인!")
    print("-" * 50)

    print("단계 3: 검색 쿼리를 임베딩할 모델을 로드합니다.")
    model_name = "jhgan/ko-sroberta-multitask"
    embeddings_model = HuggingFaceEmbeddings(model_name=model_name)
    print("모델 로드 완료:", model_name)
    print("-" * 50)
    
    print("단계 4: 사전 계산된 벡터와 문서를 ChromaDB에 직접 추가합니다.")
    db_path = "./chroma_db_precomputed"
    
    db = Chroma(
        persist_directory=db_path,
        embedding_function=embeddings_model,
        collection_name="my_precomputed_db"
    )
    
    db.add_texts(
        texts=texts,
        embeddings=vectors,  # 사전 계산된 벡터 전달
        metadatas=metadatas
    )

    print("\n벡터 데이터베이스 구축 및 저장 완료!")
    print(f"저장 위치: {db_path}")

if __name__ == "__main__":
    main()
