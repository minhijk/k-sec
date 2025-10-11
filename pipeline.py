import os
import sys
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

try:
    from db_handler import get_trivy_and_rag_analysis
    from llm_handler import get_llm
except ImportError:
    print("[오류] db_handler.py 또는 llm_handler.py를 찾을 수 없습니다. 파일 구조를 확인해주세요.")
    sys.exit(1)

# --- LLM 및 RAG 체인 초기화 ---
try:
    print(" -> [Pipeline] LLM 및 RAG 체인 구성을 시작합니다...")
    LLM = get_llm()

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
9. **(벤치마크 ID 정확성)**: '1. 위반 벤치마크' 섹션의 '[CIS/NSA/PSS 번호 또는 조항]' 부분은 반드시 [근거] 섹션에 제공된 문서의 `metadata.id` 값을 정확하게 사용해야 합니다. (예: `[CIS 5.2.7]`) 절대로 임의의 번호를 생성하지 마세요.

[근거]
{retrieved_context}

[YAML]
{yaml_content}

[질문]
{question}

# 출력 형식(항상 이 형식 유지, 섹션 제목/순서 변경 금지)
1. 위반 벤치마크
- [CIS/NSA/PSS (metadata.id 값)]: [문제 요약] (위험도) [근거번호]

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

    RAG_CHAIN = (
        RunnablePassthrough()
        | prompt
        | LLM
        | StrOutputParser()
    )
    print(" -> [Pipeline] RAG 체인이 성공적으로 구성되었습니다.")

except Exception as e:
    print(f"\n[오류] 파이프라인 초기화 중 문제가 발생했습니다: {e}")
    RAG_CHAIN = None

def format_analysis_results(analysis_results: list) -> str:
    """db_handler에서 받은 analysis_results 리스트를 LLM이 이해하기 좋은 문자열로 포맷합니다."""
    if not analysis_results:
        return "관련된 보안 지침이나 벤치마크 문서를 찾을 수 없습니다."
        
    lines = []
    for i, result in enumerate(analysis_results, start=1):
        doc = result.get('source_document', {})
        header = f"[{i}]"
        
        metadata_lines = []
        if metadata := doc.get('metadata'):
            for key, value in metadata.items():
                metadata_lines.append(f"  - {key}: {value}")
        metadata_str = "\n".join(metadata_lines)
        
        content = doc.get('content', '내용 없음')
        
        full_doc_str = f"{header}\n[METADATA]\n{metadata_str}\n[CONTENT]\n{content}"
        lines.append(full_doc_str)
        
    return "\n\n" + "="*20 + "\n\n".join(lines)

def main():
    if RAG_CHAIN is None:
        print("\n초기화 실패. 프로그램을 종료합니다.")
        return

    print("\n" + "="*60)
    print("준비 완료. 분석할 YAML 파일 경로를 입력해주세요.")
    
    while True:
        file_path = input("\nYAML 파일 경로: ").strip()

        if file_path.lower() in ["exit", "quit"]:
            break
        if not os.path.exists(file_path):
            print(" -> [오류] 파일을 찾을 수 없습니다.")
            continue
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                yaml_content = f.read()
            
            question = input("질문 (없으면 Enter): ").strip()
            if not question:
                question = "이 YAML 파일의 내용을 분석하고, 주요 설정과 잠재적인 보안 취약점에 대해 종합적으로 설명해 줘."
            
            print("\n -> [Pipeline] db_handler를 호출하여 YAML을 분석합니다...")
            # db_handler는 딕셔너리 또는 숫자 0을 반환합니다.
            analysis_data = get_trivy_and_rag_analysis(yaml_content)
            
            # 1. 취약점 없을 시 (숫자 0 반환) 처리
            if analysis_data == 0:
                print("\n[전문가 분석 답변]\n" + "-" * 20)
                print("분석 결과, 보안상 발견된 문제점이 없습니다. YAML 파일이 안전합니다.")
                print("-" * 20)
                continue

            # 2. 에러가 발생한 경우 처리
            if isinstance(analysis_data, dict) and 'error' in analysis_data:
                print(f" -> [오류] db_handler에서 문제가 발생했습니다: {analysis_data['error']}")
                continue

            # 3. 정상 분석 결과 처리
            formatted_context = format_analysis_results(analysis_data.get("analysis_results", []))
            
            input_data = {
                "retrieved_context": formatted_context,
                "question": question,
                "yaml_content": analysis_data.get("analyzed_yaml_content", ""),
            }

            print(" -> [Pipeline] 모든 정보를 종합하여 LLM에게 최종 답변 생성을 요청합니다...")
            response = RAG_CHAIN.invoke(input_data)
            
            print("\n[전문가 분석 답변]\n" + "-" * 20)
            print(response)
            print("-" * 20)
            
        except Exception as e:
            print(f" -> [오류] 처리 중 문제가 발생했습니다: {e}")

if __name__ == "__main__":
    main()