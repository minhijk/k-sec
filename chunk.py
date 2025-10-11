import json
import re
import requests
from bs4 import BeautifulSoup
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

# ✨ URL 유효성을 더 확실하게 검사하는 함수 (이전 버전보다 개선)
def check_url_validity(url: str) -> bool:
    """
    URL의 유효성을 검증합니다.
    1. HTTP 상태 코드가 404인지 확인합니다.
    2. 페이지 제목에 오류 관련 키워드가 있는지 확인합니다.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, timeout=10, headers=headers, allow_redirects=True)

        if response.status_code >= 400:
            print(f"  -> INFO: HTTP {response.status_code} 오류 발견 ({url})")
            return False

        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.string.lower() if soup.title and soup.title.string else ""
        
        error_keywords = ["404", "not found", "error", "페이지를 찾을 수 없습니다"]
        if any(keyword in title for keyword in error_keywords):
            print(f"  -> INFO: 제목에서 오류 키워드 발견 ({url})")
            return False

        return True
    except requests.exceptions.RequestException as e:
        print(f"  -> INFO: URL 연결 오류 ({url})")
        return False

# JSON 파일을 Document 객체 리스트로 변환하는 함수
def json_to_chunk(file_path: str) -> list[Document]:
    try:
        with open(file_path, 'r', encoding='utf-8') as f: 
            data = json.load(f)
    except Exception as e:
        print(f"파일 처리 중 오류 발생: {e}")
        return []

    documents = []
    url_pattern = re.compile(r'https?://[^\s,)]+')

    for item in data:
        if not item.get('id') or not item.get('title'): 
            continue
        
        # 'details' 객체가 없는 경우를 대비해 빈 딕셔너리로 처리
        details = item.get('details', {})

        # ✨ [수정됨] 새로운 JSON 구조에 맞게 데이터 추출
        page_content = f"""Title: {item.get('title', 'N/A')}
Description: {item.get('content_description', 'N/A')}
Rationale: {details.get('rationale', 'N/A')}
Audit: {details.get('audit', 'N/A')}
Remediation: {item.get('content_remediation', 'N/A')}"""

        # ✨ [수정됨] 새로운 JSON 구조에 맞게 메타데이터 구성
        metadata = {
            'id': item.get('id', ''),
            'source': item.get('source', ''),
            'category_l1': item.get('category_l1', ''),
            'category_l2': item.get('category_l2', ''),
            'impact': details.get('impact', ''),
            'default_value': details.get('default_value', ''),
            'references': details.get('references', '') # URL 처리를 위해 일단 가져옴
        }
        
        # ✨ [수정됨] URL 처리 로직 (이전보다 개선된 방식 적용)
        if metadata.get('references'):
            refs = metadata['references']
            ref_list = []

            if isinstance(refs, str):
                ref_list = url_pattern.findall(refs)
            elif isinstance(refs, list):
                # 리스트 안의 문자열에서 URL을 다시 추출
                temp_list = []
                for ref_str in refs:
                    temp_list.extend(url_pattern.findall(ref_str))
                ref_list = temp_list

            processed_refs = []
            if ref_list:
                for url in ref_list:
                    if check_url_validity(url):
                        processed_refs.append(url)
                    else:
                        processed_refs.append("https://kubernetes.io/docs/home/")
                metadata['references'] = processed_refs
            else: # URL이 없는 단순 문자열인 경우
                 metadata['references'] = refs


        # 빈 값을 가진 메타데이터 필드 제거
        metadata = {k: v for k, v in metadata.items() if v}
        doc = Document(page_content=page_content.strip(), metadata=metadata)
        documents.append(doc)

    return documents


def embed_in_batches(embeddings_model, texts, batch_size=100):
    # (이하 코드는 이전과 동일)
    all_vectors = []
    total_batches = (len(texts) + batch_size - 1) // batch_size
    
    print(f"총 {len(texts)}개 텍스트를 {batch_size} 크기로 {total_batches}개 배치로 처리합니다.")
    
    for i in range(0, len(texts), batch_size):
        batch_num = (i // batch_size) + 1
        batch = texts[i:i+batch_size]
        
        print(f"배치 {batch_num}/{total_batches} 임베딩 중... ({len(batch)}개 항목)")
        
        try:
            batch_vectors = embeddings_model.embed_documents(batch)
            all_vectors.extend(batch_vectors)
        except Exception as e:
            print(f"배치 {batch_num} 임베딩 실패: {e}")
            continue
    
    return all_vectors


if __name__ == "__main__":
    file_path = 'structured_all.json'

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            pass
    except FileNotFoundError:
        print(f"오류: '{file_path}' 파일을 찾을 수 없습니다. 파일 경로를 확인해주세요.")
        exit()

    chunk = json_to_chunk(file_path)

    if chunk:
        print(f"총 {len(chunk)}개의 Chunk 생성 완료")
        print("----------"*10)

        pre_vector_data = [{"page_content": doc.page_content, "metadata": doc.metadata} for doc in chunk]
        
        pre_vector_file = 'pre_vectors.json'
        with open(pre_vector_file, 'w', encoding='utf-8') as f:
            json.dump(pre_vector_data, f, ensure_ascii=False, indent=2)
        print(f"벡터화 전 Document 내용을 '{pre_vector_file}'에 저장 완료")
        print("----------"*10)

        model_name = "jhgan/ko-sroberta-multitask"
        embeddings_model = HuggingFaceEmbeddings(model_name=model_name)

        texts_to_embed = [doc.page_content for doc in chunk]

        print("임베딩 시작...")
        vectors = embed_in_batches(embeddings_model, texts_to_embed, batch_size=100)
        print("임베딩 완료")
        print(f"\n총 {len(vectors)}개의 벡터 생성\n")

        output_file = 'vectors.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(vectors, f, ensure_ascii=False, indent=2)
        print(f"임베딩 결과를 '{output_file}'에 저장 완료")

    else:
        print("문서 변환 실패")