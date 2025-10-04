import json
import re
import requests
from bs4 import BeautifulSoup
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
import os

def get_page_text(url: str) -> str:
    """주어진 URL의 HTML에서 모든 텍스트를 추출합니다."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, timeout=5, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        return soup.get_text()
    except requests.exceptions.RequestException:
        print(f"URL에 연결 중 오류 발생: {url}")
        return ""
    except Exception as e:
        print(f"알 수 없는 오류 발생 (URL: {url}): {e}")
        return ""

def json_to_chunk(file_path: str) -> list[Document]:
    """
    JSON 파일을 읽어 Document로 변환합니다.
    이 과정에서 'references' 필드의 URL 유효성을 검사하고 수정합니다.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"파일 처리 중 오류 발생: {e}")
        return []

    documents = []
    url_pattern = re.compile(r'https?://[^\s]+')

    for item in data:
        page_content = f"""Title: {item.get('title', 'N/A')}
Description: {item.get('description', 'N/A')}
Rationale: {item.get('rationale', 'N/A')}
Audit: {item.get('audit', 'N/A')}
Remediation: {item.get('remediation', 'N/A')}"""

        # 1. page_content를 제외한 모든 필드를 일단 메타데이터로 구성합니다.
        metadata = {k: v for k, v in item.items() if k not in ['title', 'description', 'rationale', 'audit', 'remediation']}
        metadata = {k: v for k, v in metadata.items() if v}

        # ✨✨✨ [핵심 기능 추가] ✨✨✨
        # 'references' 필드가 존재하고, 문자열일 경우에만 URL 유효성 검사를 수행합니다.
        if 'references' in metadata and isinstance(metadata.get('references'), str):
            # pdf_parser가 만든 멀티라인 문자열을 줄 단위로 분리합니다.
            ref_lines = metadata['references'].split('\n')
            processed_lines = [] # 처리된 결과를 담을 새 리스트

            for line in ref_lines:
                match = url_pattern.search(line)
                # 현재 줄에 URL이 포함되어 있는지 확인합니다.
                if match:
                    url = match.group(0)
                    page_text = get_page_text(url)
                    # 404 오류가 발생했는지 확인합니다.
                    if "404 Page not found" in page_text:
                        print(f"  -> INFO: 깨진 URL 발견 ({url}). 기본 URL로 대체합니다.")
                        # 깨진 URL이 포함된 줄 전체를 대체 URL로 바꿉니다.
                        processed_lines.append("https://kubernetes.io/docs/home/")
                    else:
                        # URL이 정상이면 원래 줄을 그대로 유지합니다.
                        processed_lines.append(line)
                else:
                    # URL이 없는 줄(예: "Page 262...")은 그대로 유지합니다.
                    processed_lines.append(line)
            
            # 처리된 줄들을 다시 하나의 멀티라인 '문자열'로 합쳐서 메타데이터를 업데이트합니다.
            metadata['references'] = '\n'.join(processed_lines)
        # ✨✨✨ [기능 추가 끝] ✨✨✨

        doc = Document(page_content=page_content.strip(), metadata=metadata)
        documents.append(doc)

    return documents

def embed_in_batches(embeddings_model, texts, batch_size=100):
    """텍스트 목록을 배치 단위로 임베딩합니다."""
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
    file_path = 'structured_cis_benchmark_v1.12.json' 
    try:
        with open(file_path, 'r', encoding='utf-8'):
            pass
    except FileNotFoundError:
        print(f"오류: '{file_path}' 파일을 찾을 수 없습니다. pdf_parser.py를 먼저 실행하세요.")
        exit()

    chunk = json_to_chunk(file_path)

    if chunk:
        print(f"총 {len(chunk)}개의 Chunk 생성 완료")
        pre_vector_data = [{"page_content": doc.page_content, "metadata": doc.metadata} for doc in chunk]
        
        pre_vector_file = 'pre_vectors.json'
        with open(pre_vector_file, 'w', encoding='utf-8') as f:
            json.dump(pre_vector_data, f, ensure_ascii=False, indent=2)
        print(f"벡터화 전 Document 내용을 '{pre_vector_file}'에 저장 완료")

        model_name = "jhgan/ko-sroberta-multitask"
        embeddings_model = HuggingFaceEmbeddings(model_name=model_name)
        
        texts_to_embed = [doc.page_content for doc in chunk]
        
        print("임베딩 시작...")
        vectors = embed_in_batches(embeddings_model, texts_to_embed, batch_size=100)
        print("임베딩 완료")

        output_file = 'vectors.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(vectors, f, ensure_ascii=False, indent=2)
        print(f"임베딩 결과를 '{output_file}'에 저장 완료")
    else:
        print("문서 변환 실패")

