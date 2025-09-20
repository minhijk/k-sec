import json
import re
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings



# JSON 파일을 Document 객체 리스트로 변환하는 함수
def json_to_chunk(file_path: str) -> list[Document]:
    try:
        with open(file_path, 'r', encoding='utf-8') as f: 
            data = json.load(f)
    except Exception as e:
        print(f"파일 처리 중 오류 발생: {e}")
        return []
    documents = []
    for item in data:
        if not item.get('id') or not item.get('title'): 
            continue
        
        # 임베딩 과정에서 벡터화할 데이터
        page_content = f"""Title: {item.get('title', 'N/A')}
Description: {item.get('description', 'N/A')}
Rationale: {item.get('rationale', 'N/A')}
Audit: {item.get('audit', 'N/A')}
Remediation: {item.get('remediation', 'N/A')}"""

        # 벡터화 하지 않는 메타데이터
        metadata = {
            'id': item.get('id', ''), 'impact': item.get('impact', ''),
            'default_value': item.get('default_value', ''), 'references': item.get('references', ''),
        }
        metadata = {k: v for k, v in metadata.items() if v}
        doc = Document(page_content=page_content.strip(), metadata=metadata)
        documents.append(doc)

    return documents



if __name__ == "__main__":
    file_path = 'structured_cis_benchmark_v1.11.1.json'

    chunk = json_to_chunk(file_path)

    if chunk:
        print(f"총 {len(chunk)}개의 Chunk")
        print("----------"*20)
        for i in range(len(chunk)):
            print(chunk[i])
            print("\n")
        # "jhgan/ko-sroberta-multitask"는 한국어 성능이 좋은 모델
        model_name = "jhgan/ko-sroberta-multitask"
        embeddings_model = HuggingFaceEmbeddings(model_name=model_name)
        
        # 각chunk에서 page_content만 추출
        texts_to_embed = [doc.page_content for doc in chunk]
        
        # 임베딩 실행
        print("임베딩 시작")
        vectors = embeddings_model.embed_documents(texts_to_embed)
        print("임베딩 완료")
        print(f"\n총 {len(vectors)}개의 벡터 생성\n")
     
    else:
        print("문서 변환 실패")