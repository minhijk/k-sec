import os
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableParallel, RunnableLambda
from langchain_core.output_parsers import StrOutputParser

# 분리된 핸들러 파일에서 객체 생성 함수를 가져옵니다.
from retriever import get_retriever
from llm_handler import get_llm

# run_analysis_tool 함수가 제거되었습니다.

def format_db_context(docs: list) -> str:
    """
    검색된 문서의 '모든 메타데이터'와 '내용'을 형식에 맞춰 문자열로 결합합니다. -> LLM 성능 향상 목적
    """
    lines = []
    for i, doc in enumerate(docs, start=1):
        header = f"[{i}]"
        
        metadata_lines = []
        if doc.metadata:
            for key, value in doc.metadata.items():
                metadata_lines.append(f"  - {key}: {value}")
        
        metadata_str = "\n".join(metadata_lines)
        content = doc.page_content
        full_doc_str = f"{header}\n[METADATA]\n{metadata_str}\n[CONTENT]\n{content}"
        lines.append(full_doc_str)

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
    # [자동 분석 결과] 섹션이 제거된 프롬프트 템플릿
    RAG_PROMPT_TEMPLATE = """
당신은 K-SEC Copilot, 쿠버네티스 보안 벤치마크 분석을 전문으로 하는 AI 전문가입니다.
제공된 [근거]와 [YAML]을 단계적으로 분석하여, 아래 규칙과 출력 형식에 맞춰 보안 평가 보고서를 생성하세요.

# 규칙
1. **(언어)**: 모든 설명(위반 요약, 위험 설명, 권장사항 등)은 반드시 자연스러운 한국어로 작성하세요.
2. **(근거 기반)**: 반드시 [근거] 섹션에 제공된 정보만을 사용하여 평가해야 합니다. 근거에 없는 내용은 언급하지 마세요.
3. **(위반 없을 시)**: [근거]를 바탕으로 어떤 위반 사항도 찾지 못했다면, '1. 위반 벤치마크' 섹션에 "- 발견된 보안 벤치마크 위반 사항 없음"이라고만 작성하고 나머지 섹션은 비워두세요.
4. **(인용)**: 모든 분석 내용 끝에는 관련된 [근거]의 번호를 모두 명시하세요. 예: `... [1]`, `... [1, 3]`
5. **(위험도)**: 위험도 라벨은 반드시 {{Critical|High|Medium|Low}} 중 하나만 사용하세요.
6. **(YAML 경로)**: '현재 설정 문제' 섹션의 YAML 경로는 `spec.containers[0].securityContext` 와 같이 점(.) 표기법을 사용하세요.
7. **(수정안 범위)**: '권장 수정안'의 코드 블록에는 전체 YAML이 아닌, **수정에 필요한 최소한의 부분**만 `yaml` 형식으로 포함하세요.
8. **(수정안 없을시)**: '수정 코드가 없다면, '3. 권장 수정안 (코드만) 섹션에 "- 수정 코드 없음"이라고만 작성하고 나머지 섹션은 비워두세요.


[근거]
{retrieved_context}

[YAML]
{yaml_content}


[질문]
{question}

# 출력 형식(항상 이 형식 유지, 섹션 제목/순서 변경 금지)
1. 위반 벤치마크
- [CIS/NSA/PSS 번호 또는 조항]: [문제 요약] (위험도) [근거번호]

2. 현재 설정 문제
- [YAML 경로]=[값] → [위험 설명] [근거번호]

3. 권장 수정안 (코드만)
```yaml
# 수정전:
# (생략 가능)

# 수정후:
# 여기에 권장 설정 YAML만 제시
```

4. 추가 권장사항
- [간단 문장] [근거번호]
""".strip()
    prompt = ChatPromptTemplate.from_template(RAG_PROMPT_TEMPLATE)

    # analysis_result가 제거된 검색 쿼리 생성 함수
    def create_retrieval_query(input_dict: dict) -> str:
        return f"""
[사용자 질문]: {input_dict['question']}
[YAML 내용]: {input_dict['yaml_content']}
"""
    
    # analysis_result가 제거된 RAG 체인
    rag_chain = (
        RunnableParallel({
            "retrieved_context": RunnableLambda(create_retrieval_query) | retriever | format_db_context, 
            "question": lambda x: x["question"],
            "yaml_content": lambda x: x["yaml_content"],
        })
        | prompt
        | llm
        | StrOutputParser()
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

            # analysis_result 관련 로직이 제거되고, input_data가 간소화됨
            input_data = {
                "question": question,
                "yaml_content": yaml_content,
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
