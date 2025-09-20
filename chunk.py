import json
import re
import requests
from bs4 import BeautifulSoup
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings


# 특정 URL의 전체 텍스트를 가져오는 함수
def get_page_text(url: str) -> str:
    """
    주어진 URL의 HTML에서 모든 텍스트를 추출합니다.
    서버 응답 상태 코드와 관계없이 페이지의 모든 텍스트를 확인합니다.
    """
    try:
        # 일부 웹사이트에서 차단하는 것을 방지하기 위해 User-Agent 헤더 추가
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, timeout=5, headers=headers)
        
        # 상태 코드와 관계없이 HTML 파싱을 시도하여 모든 텍스트를 가져옴
        soup = BeautifulSoup(response.text, "html.parser")
        return soup.get_text()
    except requests.exceptions.RequestException:
        # 네트워크 오류, 타임아웃 등의 문제 발생 시 빈 문자열 반환
        print(f"URL에 연결 중 오류 발생: {url}")
        return ""
    except Exception as e:
        # 그 외 예상치 못한 오류 발생 시
        print(f"알 수 없는 오류 발생 (URL: {url}): {e}")
        return ""


# JSON 파일을 Document 객체 리스트로 변환하는 함수
def json_to_chunk(file_path: str) -> list[Document]:
    try:
        with open(file_path, 'r', encoding='utf-8') as f: 
            data = json.load(f)
    except Exception as e:
        print(f"파일 처리 중 오류 발생: {e}")
        return []
        
    documents = []
    # URL을 찾기 위한 정규식 컴파일
    url_pattern = re.compile(r'https?://[^\s]+')

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
            'id': item.get('id', ''), 
            'impact': item.get('impact', ''),
            'default_value': item.get('default_value', ''), 
            'references': item.get('references', ''),
        }

        # references가 여러개일 경우 처리
        if metadata.get('references'):
            refs = metadata['references']
            if isinstance(refs, str):
                refs = [refs]
            elif not isinstance(refs, list):
                refs = []

            new_refs = []
            for ref in refs:
                match = url_pattern.search(ref)
                
                if match:
                    url = match.group(0)
                    page_text = get_page_text(url)
                    # 페이지 전체 텍스트에 "404 Page not found" 문자열이 포함되어 있는지 확인
                    if "404 Page not found" in page_text:
                        new_refs.append("https://kubernetes.io/docs/home/")
                    else:
                        new_refs.append(ref) # 원래의 ref 유지
                else:
                    # URL이 없는 경우, 원래 ref를 그대로 추가
                    new_refs.append(ref)
            metadata['references'] = new_refs

        metadata = {k: v for k, v in metadata.items() if v}
        doc = Document(page_content=page_content.strip(), metadata=metadata)
        documents.append(doc)

    return documents


if __name__ == "__main__":
    # JSON 파일 경로를 설정해주세요.
    # 예시: structured_cis_benchmark_v1.11.1.json
    file_path = 'structured_cis_benchmark_v1.11.1.json'

    # 파일이 존재하는지 확인
    try:
        with open(file_path, 'r') as f:
            pass
    except FileNotFoundError:
        print(f"오류: '{file_path}' 파일을 찾을 수 없습니다. 파일 경로를 확인해주세요.")
        exit()

    chunk = json_to_chunk(file_path)

    if chunk:
        print(f"총 {len(chunk)}개의 Chunk 생성 완료")
        print("----------"*10)
        
        # 벡터화 전 Document 정보 저장
        pre_vector_data = []
        for i, doc in enumerate(chunk):
            doc_info = {
                "page_content": doc.page_content,
                "metadata": doc.metadata
            }
            pre_vector_data.append(doc_info)
            # 모든 내용을 출력하면 너무 길어지므로 첫 3개만 출력
            if i < 3:
                print(json.dumps(doc_info, indent=2, ensure_ascii=False))
                print("\n")
        
        pre_vector_file = 'pre_vectors.json'
        with open(pre_vector_file, 'w', encoding='utf-8') as f:
            json.dump(pre_vector_data, f, ensure_ascii=False, indent=2)
        print(f"벡터화 전 Document 내용을 '{pre_vector_file}'에 저장 완료")
        print("----------"*10)

        # "jhgan/ko-sroberta-multitask"는 한국어 성능이 좋은 모델
        model_name = "jhgan/ko-sroberta-multitask"
        embeddings_model = HuggingFaceEmbeddings(model_name=model_name)
        
        # 각 chunk에서 page_content만 추출
        texts_to_embed = [doc.page_content for doc in chunk]
        
        # 임베딩 실행
        print("임베딩 시작...")
        vectors = embeddings_model.embed_documents(texts_to_embed)
        print("임베딩 완료")
        print(f"\n총 {len(vectors)}개의 벡터 생성\n")

        # 임베딩 결과 저장
        output_file = 'vectors.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(vectors, f, ensure_ascii=False, indent=2)
        print(f"임베딩 결과를 '{output_file}'에 저장 완료")
    
    else:
        print("문서 변환 실패")