import os
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableParallel, RunnableLambda
from langchain_core.output_parsers import StrOutputParser

# 분리된 핸들러 파일에서 객체 생성 함수를 가져옵니다.
from .db_handler import get_retriever
from .llm_handler import get_llm


def run_analysis_tool(yaml_content: str) -> str:
    if "privileged: true" in yaml_content:
        return "[자동 분석 결과] 'privileged: true' 설정이 탐지되었습니다..."
    return "[자동 분석 결과] 특이한 보안 취약점은 발견되지 않았습니다."

def format_db_context(docs: list) -> str:
    """
    검색된 문서의 '모든 메타데이터'와 '내용'을 형식에 맞춰 문자열로 결합합니다. -> LLM 성능 향상 목적
    """
    lines = []
    for i, doc in enumerate(docs, start=1):
        # 1. 문서 번호로 시작
        header = f"[{i}]"
        
        # 2. 메타데이터의 모든 항목을 "key: value" 형식으로 변환
        metadata_lines = []
        if doc.metadata:
            for key, value in doc.metadata.items():
                metadata_lines.append(f"  - {key}: {value}")
        
        metadata_str = "\n".join(metadata_lines)

        # 3. 원본 내용(page_content) 추출
        content = doc.page_content

        # 4. 모든 정보를 하나의 문자열로 결합
        full_doc_str = f"{header}\n[METADATA]\n{metadata_str}\n[CONTENT]\n{content}"
        lines.append(full_doc_str)

    # 각 문서 정보를 구분선으로 나누어 최종 반환
    return "\n\n" + "="*20 + "\n\n".join(lines)


def main():
    print("--- K-Sec Copilot (모듈 분리 버전): RAG 파이프라인 시작 ---")

    # --- RAG 컴포넌트 로드 (핸들러 호출) ---
    try:
        retriever = get_retriever()
        llm = get_llm()
    except Exception:
        print("\n초기화 실패. 프로그램을 종료합니다.")
        return

    # --- 프롬프트 및 RAG 체인 구성 ---
    RAG_PROMPT_TEMPLATE = """
당신은 YAML 파일을 분석하고 보안 취약점을 설명하는 쿠버네티스 보안 전문가 AI입니다.
주어진 [배경 지식]을 반드시 참고하여 답변해야 합니다. 답변은 [자동 분석 결과]와 [YAML 파일 내용]을 모두 고려하여 종합적으로 생성해야 합니다.

답변은 다음 규칙을 엄격히 준수해야 합니다:
1. 모든 근거는 [배경 지식]에서만 가져와야 합니다. 배경 지식에 없는 내용은 "관련 정보를 찾을 수 없습니다."라고 답변하세요.
2. 답변의 각 문장 끝에, 그 근거가 된 [배경 지식]의 번호를 대괄호로 `[번호]` 형식으로 명시해야 합니다.
3. 최종 답변은 한국어로, 전문가처럼 명확하고 간결하게 작성하세요.

---
[배경 지식]
{retrieved_context}

[YAML 파일 내용]
{yaml_content}

[자동 분석 결과]
{analysis_result}

[사용자 질문]
{question}
---

[전문가 답변]
""".strip()
    prompt = ChatPromptTemplate.from_template(RAG_PROMPT_TEMPLATE)

    def create_retrieval_query(input_dict: dict) -> str:
        return f"""
[사용자 질문]: {input_dict['question']}
[YAML 내용]: {input_dict['yaml_content']}
[분석 결과]: {input_dict['analysis_result']}
"""
    rag_chain = (
        RunnableParallel({                          #검색에 사용될 데이터 | 검색기    | 출처포멧터
            "retrieved_context": RunnableLambda(create_retrieval_query) | retriever | format_db_context, 
            "question": lambda x: x["question"], # 사용자 질문
            "yaml_content": lambda x: x["yaml_content"], # 원본 YAML 파일 내용
            "analysis_result": lambda x: x["analysis_result"], # YAMl파일 분석 결과
        }) # 프롬프트 병렬적으로 준비
        | prompt # 프롬프트 생성
        | llm    # 프롬프트 llm에 전달 -> 답변 생성
        | StrOutputParser() # 최종 단변 문자열로 생성
    )
    print("RAG 체인이 성공적으로 구성되었습니다.")
    

    print("\n" + "="*60)
    print("준비 완료. 분석할 YAML 파일 경로를 입력해주세요.")
    while True:
        file_path = input("\nYAML 파일 경로: ").strip()

        if file_path.lower() in ["exit", "quit"]: break
        if not os.path.exists(file_path):
            print(" -> [오류] 파일을 찾을 수 없습니다.")
            continue
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                yaml_content = f.read()
            question = input("질문 (없으면 Enter): ").strip()
            if not question:
                question = "이 YAML 파일의 내용을 분석하고, 주요 설정과 잠재적인 보안 취약점에 대해 종합적으로 설명해 줘."
                print(" -> 정보: 질문이 없어 기본 분석을 수행합니다.")

            analysis_result = run_analysis_tool(yaml_content)
            input_data = {
                "question": question,
                "yaml_content": yaml_content,
                "analysis_result": analysis_result
            }

            print("\n분석 중...")
            response = rag_chain.invoke(input_data)
            print("\n[전문가 분석 답변]\n" + "-" * 20)
            print(response)
            print("-" * 20)
        except Exception as e:
            print(f" -> [오류] 처리 중 문제가 발생했습니다: {e}")


if __name__ == "__main__":
    main()