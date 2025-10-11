# _url_validator.py

import re
import requests
from typing import List

def validate_urls_in_text(text: str, fallback_url: str) -> str:
    """
    주어진 텍스트(단일 또는 여러 줄)에 포함된 모든 URL의 유효성을 검사합니다.
    유효하지 않은 URL(e.g., 4xx/5xx 에러, 타임아웃)은 지정된 fallback URL로 대체합니다.

    Args:
        text (str): URL을 포함하고 있는 원본 문자열.
        fallback_url (str): 유효하지 않은 URL을 대체할 기본 URL.

    Returns:
        str: 유효하지 않은 URL이 대체된 새로운 문자열. 원본과 동일할 수 있음.
    """
    if not text or not isinstance(text, str):
        return ""

    # 정규식을 사용하여 텍스트에서 모든 URL을 추출합니다.
    # 공백, 쉼표, 세미콜론, 따옴표 등을 URL의 끝으로 간주합니다.
    urls: List[str] = re.findall(r'https?://[^\s,;"\'\\]+', text)
    
    if not urls:
        return text

    modified_text = text
    
    for url in set(urls): # 중복된 URL은 한 번만 검사하여 효율성 증대
        try:
            # HEAD 요청을 사용하여 전체 페이지를 다운로드하지 않고 상태 코드만 확인 (효율적)
            response = requests.head(url, timeout=5, allow_redirects=True)
            
            # 400번대(클라이언트 오류) 또는 500번대(서버 오류) 코드가 반환되면 유효하지 않은 URL로 간주
            if response.status_code >= 400:
                print(f"   ⚠️ 유효하지 않은 URL 발견 ({response.status_code}): {url} -> 대체합니다.")
                modified_text = modified_text.replace(url, fallback_url)
                
        except requests.RequestException as e:
            # 타임아웃, DNS 조회 실패 등 네트워크 관련 예외 처리
            print(f"   ❌ URL 연결 오류: {url} ({e.__class__.__name__}) -> 대체합니다.")
            modified_text = modified_text.replace(url, fallback_url)
            
    return modified_text