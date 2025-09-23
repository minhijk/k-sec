# --- 1. 필요한 라이브러리 임포트 ---
# LangChain에서 Ollama 모델을 사용하기 위한 클래스
from langchain_community.llms import Ollama
# LLM에게 보낼 질문(프롬프트)의 형식을 정의하기 위한 클래스
from langchain_core.prompts import ChatPromptTemplate

def main():
    """
    Ollama를 사용하여 로컬 LLM 모델(Qwen3)을 실행하고,
    LangChain으로 제어하는 기본 과정을 시연합니다.
    """
    print("--- Ollama LLM(Qwen3) 연동 테스트 시작 ---")

    # --- 2. 사용할 LLM 모델 설정 ---
    # Ollama 클래스의 인스턴스를 생성합니다.
    # model 이름을 "qwen3:latest"로 변경합니다.
    try:
        print("\n[단계 1/3] 로컬 LLM (qwen3:latest) 모델을 로드합니다...")
        llm = Ollama(model="qwen3:latest")
        print(" -> 모델 로드 성공!")
    except Exception as e:
        print(f"\n[오류] Ollama 모델 로드에 실패했습니다: {e}")
        print(" -> Ollama 애플리케이션이 실행 중인지, 'ollama pull qwen3:latest' 명령어로 모델을 다운로드했는지 확인해주세요.")
        return

    # --- 3. 프롬프트 템플릿 생성 ---
    print("\n[단계 2/3] LLM에게 보낼 프롬프트 템플릿을 생성합니다...")
    prompt = ChatPromptTemplate.from_template(
        "당신은 쿠버네티스 보안 전문가입니다. 다음 질문에 대해 한국어로 간결하게 답변해주세요:\n\n질문: {input}"
    )
    print(" -> 프롬프트 템플릿 생성 완료!")

    # --- 4. LangChain의 LCEL을 사용하여 체인(Chain) 구성 ---
    print("\n[단계 3/3] 프롬프트와 LLM 모델을 체인으로 연결합니다...")
    chain = prompt | llm
    print(" -> 체인 구성 완료!")

    # --- 5. 사용자 입력 루프 시작 ---
    print("\n" + "="*50)
    print("이제 AI 모델과 대화를 시작할 수 있습니다. (종료하려면 'exit' 또는 'quit'을 입력하세요)")
    
    while True:
        # 사용자로부터 질문을 입력받습니다.
        question = input("\n당신의 질문: ")

        # 종료 명령어를 확인합니다.
        if question.lower() in ["exit", "quit"]:
            print("프로그램을 종료합니다.")
            break
        
        # 입력된 질문으로 체인을 실행하고 답변을 받습니다.
        response = chain.invoke({"input": question})
        
        print("\n[AI 답변]")
        print("-" * 20)
        print(response)
        print("-" * 20)

if __name__ == "__main__":
    main()