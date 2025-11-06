import os
import json
import re
from collections import Counter
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import AIMessage, HumanMessage

from llm_handler import get_llm
from db_handler_es import get_trivy_and_rag_analysis


LLM = get_llm()

def get_prompt_chain(mode: str = "user"):
    """모드별 프롬프트 체인 생성"""
    template_file = (
        "prompt_template_expert.md" if mode == "expert" else "prompt_template.md"
    )
    try:
        with open(template_file, "r", encoding="utf-8") as f:
            prompt_text = f.read()
        prompt = ChatPromptTemplate.from_template(prompt_text)
        chain = RunnablePassthrough() | prompt | LLM | StrOutputParser()
        print(f"[INIT] ✅ LLM 체인 초기화 성공 ({mode} mode, {template_file})")
        return chain
    except Exception as e:
        print(f"[INIT] ❌ 프롬프트 로드 실패 ({template_file}): {e}")
        raise e


def get_chat_chain(mode: str = "user"):
    """모드별 채팅 체인 생성"""
    if mode == "expert":
        system_prompt = """당신은 K-SEC Copilot 전문가 모드입니다.
        이미 사용자와 초기 분석에 대한 대화를 나누었습니다.
        제공된 [대화 기록]을 바탕으로 사용자의 [새로운 질문]에 대해 답변하세요.
        
        **중요: 전문가 모드 답변 규칙**
        - 코드 수정이 필요한 경우 Diff 형식 사용 권장
        - 기술적으로 상세하고 정확하게 설명
        - 보안 영향을 구체적으로 분석
        
        [초기 분석 결과]는 대화의 전체 맥락이니 참고하세요."""
    else:
        system_prompt = """당신은 K-SEC Copilot, 쿠버네티스 보안 전문가입니다.
        이미 사용자와 초기 분석에 대한 대화를 나누었습니다.
        제공된 [대화 기록]을 바탕으로 사용자의 [새로운 질문]에 대해 친절하고 상세하게 답변하세요.
        [초기 분석 결과]는 대화의 전체 맥락이니 참고하세요."""
    
    chat_prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("user", "[초기 분석 결과]\n{initial_analysis}"),
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "[새로운 질문]\n{new_question}"),
    ])
    
    return chat_prompt | LLM | StrOutputParser()


print(" -> [System] 초기 분석 및 채팅 체인 구성 준비 완료.")


def format_analysis_results(analysis_results: list) -> str:
    """
    RAG 검색 결과를 [i]/[METADATA]/[CONTENT] 블록 포맷으로 직렬화.
    """
    if not analysis_results:
        return "관련된 보안 지침이나 벤치마크 문서를 찾을 수 없습니다."
    lines = []
    for i, result in enumerate(analysis_results, start=1):
        doc = result.get('source_document', {}) or {}
        header = f"[{i}]"

        es_hit = doc.get('metadata', {}) or {}
        source_field = doc.get('_source', {}) or {}
        metadata = source_field.get('metadata') or {}
        content = source_field.get('content', '내용 없음')

        metadata_lines = []
        for key, value in metadata.items():
            metadata_lines.append(f"  - {key}: {value}")
        metadata_str = "\n".join(metadata_lines)

        content = doc.get('content', '내용 없음')
        full_doc_str = f"{header}\n[METADATA]\n{metadata_str}\n[CONTENT]\n{content}"
        lines.append(full_doc_str)
    return "\n\n" + "="*20 + "\n\n".join(lines)


def debug_source_counts(analysis_results: list):
    """
    retrieved_context에 포함된 출처 비율 확인(편향 진단용 로그).
    """
    if not analysis_results:
        print("[RAG] source counts: {} (no results)")
        return
    c = Counter()
    for r in analysis_results:
        doc = r.get('source_document', {}) or {}
        es_hit = doc.get('metadata', {}) or {}
        source_field = doc.get('_source', {}) or {}

        meta = source_field.get('metadata') or {}
        src = meta.get('source') or 'UNKNOWN'
        c[src] += 1
    print("[RAG] source counts:", dict(c))


def format_references(analysis_results: list) -> str:
    """
    RAG 검색 결과에서 참고 자료 리스트를 [n]: source (ID: id) 형태로 생성.
    """
    if not analysis_results:
        return "참고 자료를 찾을 수 없습니다."
    
    lines = []
    for i, result in enumerate(analysis_results, start=1):
        doc = result.get('source_document', {}) or {}
        
        es_hit = doc.get('metadata', {}) or {}
        source_field = es_hit.get('_source', {}) or {}
        metadata = source_field.get('metadata') or {}
        
        source_file = metadata.get('source', 'UNKNOWN_SOURCE')
        doc_id = metadata.get('id', 'UNKNOWN_ID') 
        
        lines.append(f"{i}. {source_file} (ID: {doc_id})")
        
    return "\n".join(lines)


# 금지/교정 패턴: 틀린 결론 나오면 1회 재시도 트리거
FORBIDDEN_PATTERNS = [
    r"localhostProfile:\s*docker/default",
    r"type\s*:\s*docker\s*/\s*default",
    r"RuntimeDefault[^.\n]*취약",
    r"\b1024\s*이상\b[^.\n]*NET[_-]?BIND[_-]?SERVICE"
]


def needs_retry(text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in FORBIDDEN_PATTERNS)


def sanitize_output(text: str) -> str:
    """
    최종 출력에서 남을 수 있는 경미한 표현 오류를 안전하게 교정.
    """
    text = re.sub(
        r"(seccompProfile:\s*\n(?:[^\n]*\n)*?\btype\s*:\s*)docker\s*/\s*default",
        r"\1RuntimeDefault", text, flags=re.IGNORECASE
    )
    text = re.sub(r"\b1024\s*이상\b", "1024 미만(≤1023)", text)
    return text


def post_validate(text: str, mode: str = "user") -> str:
    """
    핵심 기술 오류만 검증 (원본 방식 - 모드별 검증 제거)
    """
    problems = []
    
    # 공통 검증: 치명적 기술 오류만
    if re.search(r"type\s*:\s*docker\s*/\s*default", text, re.IGNORECASE):
        problems.append("잘못된 seccomp type 제안: docker/default")
    if re.search(r"RuntimeDefault[^.\n]*취약", text):
        problems.append("RuntimeDefault를 취약으로 분류")
    if re.search(r"\b1024\s*이상\b[^.\n]*NET[_-]?BIND", text):
        problems.append("NET_BIND_SERVICE 포트 범위 오표기")
    
    # 모드별 검증 제거 (과도한 간섭 방지)

    if problems:
        banner = "⚠️ 출력 자동 점검에서 다음을 교정/경고했습니다:\n- " + "\n- ".join(problems) + "\n\n"
        return banner + text
    return text


def prepare_analysis(yaml_content: str, mode: str = "user") -> dict:
    """[사전 처리] YAML 파일을 받아 Trivy 스캔 및 RAG 검색을 미리 수행하고 결과를 반환합니다."""
    try:
        analysis_data = get_trivy_and_rag_analysis(yaml_content)

        if analysis_data == 0:
            return {"status": "no_issues", "prepared_data": None}
        if 'error' in analysis_data:
            return {"error": f"db_handler 오류: {analysis_data['error']}"}

        analysis_results = analysis_data.get("analysis_results", [])
        debug_source_counts(analysis_results)

        formatted_context = format_analysis_results(analysis_data.get("analysis_results", []))
        formatted_references = format_references(analysis_results)

        ctx_lower = formatted_context.lower()
        has_seccomp = ("seccomp" in ctx_lower) or ("runtimedefault" in ctx_lower)
        has_netbind = ("net_bind_service" in ctx_lower) or ("cap_net_bind_service" in ctx_lower)

        policy_facts = (
            "- seccompProfile.type: RuntimeDefault 는 권장(OK)이며 취약 아님.\n"
            "- Localhost 제안은 실제 커스텀 프로파일 파일 경로/이름이 근거/입력에 있을 때만.\n"
            "- NET_BIND_SERVICE 는 80/443 직접 바인딩 필요 없으면 제거 권장, "
            "필요하면 유지 + (고포트→Service/Ingress 매핑) 대안 병기.\n"
            "- NET_BIND_SERVICE 는 1024 미만(≤1023) 포트 바인딩 권한.\n"
            f"- 컨텍스트에 seccomp 근거 존재: {has_seccomp}.\n"
            f"- 컨텍스트에 NET_BIND_SERVICE 근거 존재: {has_netbind}."
        )

        prepared_data = {
            "retrieved_context": formatted_context,
            "yaml_content": analysis_data.get("analyzed_yaml_content", ""),
            "policy_facts": policy_facts,
            "formatted_references": formatted_references,
        }
        return {"status": "success", "prepared_data": prepared_data}
    except Exception as e:
        return {"error": f"분석 준비 중 오류 발생: {str(e)}"}


def generate_analysis_answer(prepared_data: dict, question: str, mode: str = "user") -> dict:
    """[실시간 답변] 미리 준비된 데이터와 사용자의 질문으로 LLM 답변을 생성합니다."""
    try:
        chain = get_prompt_chain(mode)
        input_data = prepared_data.copy()
        input_data["question"] = question

        response = chain.invoke(input_data)

        if needs_retry(response):
            correction_hint = (
                "\n[교정 힌트]\n"
                "- RuntimeDefault는 권장(OK)이며 취약 아님.\n"
                "- Localhost 제안은 실제 커스텀 프로파일 파일 경로가 근거/입력에 있을 때만.\n"
                "- NET_BIND_SERVICE는 1024 미만(≤1023) 포트 권한.\n"
                "위 사실에 반하는 진술을 제거/수정하여 다시 작성하세요."
            )
            input_data["question"] = f"{question}\n{correction_hint}"
            response = chain.invoke(input_data)

        response = sanitize_output(response)
        response = post_validate(response, mode)
        return {"result": response}
    except Exception as e:
        return {"error": f"답변 생성 중 오류 발생: {str(e)}"}


def continue_chat(initial_analysis: str, chat_history: list, new_question: str, mode: str = "user") -> dict:
    """이전 대화 기록을 바탕으로 후속 질문에 답변합니다 (모드 지원)."""
    try:
        chat_chain = get_chat_chain(mode)
        
        if not chat_chain:
            return {"error": "채팅 체인이 초기화되지 않았습니다."}
        
        processed_history = []
        for msg in chat_history:
            if msg["role"] == "user":
                processed_history.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                processed_history.append(AIMessage(content=msg["content"]))

        response = chat_chain.invoke({
            "initial_analysis": initial_analysis,
            "chat_history": processed_history,
            "new_question": new_question,
        })
        
        # 채팅 응답도 검증
        response = post_validate(response, mode)
        return {"result": response}
    except Exception as e:
        return {"error": f"채팅 처리 중 오류 발생: {str(e)}"}