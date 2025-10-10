import json
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import AIMessage, HumanMessage

from llm_handler import get_llm
from db_handler import get_trivy_and_rag_analysis

# --- 전역 LLM 및 체인 객체 ---
try:
    LLM = get_llm()

    # 1. 초기 분석을 위한 프롬프트
    with open("prompt_template.md", "r", encoding="utf-8") as f:
        INITIAL_PROMPT_TEMPLATE = f.read()
    initial_prompt = ChatPromptTemplate.from_template(INITIAL_PROMPT_TEMPLATE)

    INITIAL_RAG_CHAIN = (
        RunnablePassthrough()
        | initial_prompt
        | LLM
        | StrOutputParser()
    )

    # 2. 후속 채팅을 위한 프롬프트
    CHAT_PROMPT_TEMPLATE = ChatPromptTemplate.from_messages([
        ("system", """당신은 K-SEC Copilot, 쿠버네티스 보안 전문가입니다. 
        이미 사용자와 초기 분석에 대한 대화를 나누었습니다. 
        제공된 [대화 기록]을 바탕으로 사용자의 [새로운 질문]에 대해 친절하고 상세하게 답변하세요.
        [초기 분석 결과]는 대화의 전체 맥락이니 참고하세요."""),
        ("user", "[초기 분석 결과]\n{initial_analysis}"),
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "[새로운 질문]\n{new_question}"),
    ])

    CHAT_CHAIN = CHAT_PROMPT_TEMPLATE | LLM | StrOutputParser()

    print(" -> [System] 초기 분석 및 채팅 체인이 모두 성공적으로 구성되었습니다.")
except Exception as e:
    print(f"\n[오류] 파이프라인 초기화 중 문제가 발생했습니다: {e}")
    INITIAL_RAG_CHAIN = None
    CHAT_CHAIN = None

def format_analysis_results(analysis_results: list) -> str:
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


# 1단계: 파일 업로드 시점에 호출. 시간 소모가 큰 작업을 여기서 미리 처리.
def prepare_analysis(yaml_content: str) -> dict:
    """[사전 처리] YAML 파일을 받아 Trivy 스캔 및 RAG 검색을 미리 수행하고 결과를 반환합니다."""
    try:
        # DB에서 Trivy 스캔 및 관련 문서 검색 (가장 시간이 오래 걸리는 부분)
        analysis_data = get_trivy_and_rag_analysis(yaml_content)
        
        if analysis_data == 0:
            return {"status": "no_issues", "prepared_data": None}
        if 'error' in analysis_data:
            return {"error": f"db_handler 오류: {analysis_data['error']}"}

        # 검색된 컨텍스트를 LLM에게 전달할 형태로 포맷팅
        formatted_context = format_analysis_results(analysis_data.get("analysis_results", []))
        
        # 다음 단계(답변 생성)에 즉시 사용할 수 있도록 데이터를 정리하여 반환
        prepared_data = {
            "retrieved_context": formatted_context,
            "yaml_content": analysis_data.get("analyzed_yaml_content", ""),
        }
        return {"status": "success", "prepared_data": prepared_data}
    except Exception as e:
        return {"error": f"분석 준비 중 오류 발생: {str(e)}"}

# 2단계: 사용자가 질문을 입력했을 때 호출.
def generate_analysis_answer(prepared_data: dict, question: str) -> dict:
    """[실시간 답변] 미리 준비된 데이터와 사용자의 질문으로 LLM 답변을 생성합니다."""
    try:
        # 미리 준비된 데이터에 사용자의 질문만 추가
        input_data = prepared_data.copy()
        input_data["question"] = question
        
        # LLM 호출 (분석이 끝나있어 이 부분은 매우 빠름)
        response = INITIAL_RAG_CHAIN.invoke(input_data)
        return {"result": response}
    except Exception as e:
        return {"error": f"답변 생성 중 오류 발생: {str(e)}"}



def continue_chat(initial_analysis: str, chat_history: list, new_question: str) -> dict:
    """이전 대화 기록을 바탕으로 후속 질문에 답변합니다."""
    if not CHAT_CHAIN:
        return {"error": "채팅 체인이 초기화되지 않았습니다."}
    try:
        # LangChain 형식에 맞게 메시지 객체 리스트 생성
        processed_history = []
        for msg in chat_history:
            if msg["role"] == "user":
                processed_history.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                processed_history.append(AIMessage(content=msg["content"]))

        response = CHAT_CHAIN.invoke({
            "initial_analysis": initial_analysis,
            "chat_history": processed_history,
            "new_question": new_question,
        })
        return {"result": response}
    except Exception as e:
        return {"error": f"채팅 처리 중 오류 발생: {str(e)}"}

