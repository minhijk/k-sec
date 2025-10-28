import os
from langchain_openai import ChatOpenAI

def get_llm():
    """
    코드에 직접 입력된 API 키와 Base URL을 사용하여
    OpenAI 호환 API를 사용하는 LLM 객체를 생성하고 반환합니다.
    """
    try:
        # <<< 수정된 부분 >>>
        # 이곳에 API 키와 Base URL을 직접 입력합니다.
        # 환경 변수를 더 이상 사용하지 않습니다.
        
        api_key = "sk-2a4f43c6815f45648c5285b4fe877fde"
        base_url = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

        # API 키가 비어 있는지 확인
        if not api_key or "API_키" in api_key:
            raise ValueError("[오류] API 키가 코드에 직접 입력되지 않았습니다.")
        
        # LangChain의 ChatOpenAI 클래스를 사용하여 LLM 객체를 생성합니다.
        llm = ChatOpenAI(
            model="qwen-flash",
            api_key=api_key,
            base_url=base_url,
            temperature=0.1
        )
        
        print(" -> API 기반 LLM 모델 로드 성공! (직접 입력 방식)")
        return llm
    
    except Exception as e:
        print(f"\n[오류] API LLM 모델 로드에 실패했습니다: {e}")
        raise e