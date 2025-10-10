import streamlit as st
import requests

# --- 페이지 설정 ---
st.set_page_config(
    page_title="K-SEC Copilot",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 백엔드 서버 주소 ---
BACKEND_PREPARE_URL = "http://127.0.0.1:8000/prepare-analysis"
BACKEND_GENERATE_URL = "http://127.0.0.1:8000/generate-answer"
BACKEND_CHAT_URL = "http://127.0.0.1:8000/chat"

# --- 세션 상태 초기화 ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "analysis_task_id" not in st.session_state:
    st.session_state.analysis_task_id = None
if "initial_analysis_result" not in st.session_state:
    st.session_state.initial_analysis_result = ""
if "analysis_complete" not in st.session_state:
    st.session_state.analysis_complete = False

# --- 로직 함수 ---
def handle_file_upload():
    """파일 업로더의 on_change 콜백. 백엔드에 사전 분석을 요청합니다."""
    if st.session_state.file_uploader_key:
        uploaded_file = st.session_state.file_uploader_key
        try:
            # 사전 분석이 이미 시작되었다면 다시 요청하지 않음
            if st.session_state.analysis_task_id is None:
                st.info("파일을 수신했습니다. 백그라운드에서 분석을 준비합니다...")
                files = {'file': (uploaded_file.name, uploaded_file.getvalue(), 'application/x-yaml')}
                response = requests.post(BACKEND_PREPARE_URL, files=files)
                response.raise_for_status()
                task_id = response.json().get("task_id")
                st.session_state.analysis_task_id = task_id
        except requests.exceptions.RequestException as e:
            st.error(f"파일 준비 중 오류가 발생했습니다: {e}")
            st.session_state.analysis_task_id = None

# --- 사이드바 UI ---
with st.sidebar:
    st.title("🛡️ K-SEC Copilot")
    st.markdown("---")

    if st.session_state.analysis_complete:
        st.info("현재 분석이 완료되었습니다.")
        if st.button("🔄️ 새 분석 시작하기", use_container_width=True):
            # 모든 세션 상태 초기화
            keys_to_delete = list(st.session_state.keys())
            for key in keys_to_delete:
                del st.session_state[key]
            st.rerun()
    
    st.header("1. 분석 설정")
    uploaded_file = st.file_uploader(
        "분석할 쿠버네티스 YAML 파일을 업로드하세요.",
        type=["yaml", "yml"],
        disabled=st.session_state.analysis_complete,
        on_change=handle_file_upload,
        key='file_uploader_key'
    )
    
    default_question = "이 YAML 파일의 내용을 분석하고, 주요 설정과 잠재적인 보안 취약점에 대해 종합적으로 설명해 줘."
    question = st.text_area(
        "분석 요청 또는 질문:",
        value=default_question, height=100,
        disabled=st.session_state.analysis_complete
    )

    if st.button("🚀 분석 시작!", type="primary", use_container_width=True, disabled=st.session_state.analysis_complete):
        if st.session_state.analysis_task_id and question:
            with st.spinner("전문가가 최종 분석 보고서를 작성 중입니다... (사전 분석 결과에 따라 더 빠를 수 있습니다)"):
                try:
                    payload = {"task_id": st.session_state.analysis_task_id, "question": question}
                    response = requests.post(BACKEND_GENERATE_URL, json=payload)
                    response.raise_for_status()
                    result_data = response.json()

                    if "error" in result_data:
                        st.error(result_data["error"])
                    else:
                        st.session_state.analysis_complete = True
                        st.session_state.initial_analysis_result = result_data.get("result", "")
                        st.session_state.messages = [{"role": "user", "content": question}, {"role": "assistant", "content": st.session_state.initial_analysis_result}]
                        st.rerun()

                except requests.exceptions.RequestException as e:
                    st.error(f"백엔드 서버와 통신 중 오류가 발생했습니다: {e}")
        else:
            st.warning("먼저 YAML 파일을 업로드하고 질문을 입력해주세요.")

# --- 메인 화면 UI ---
if not st.session_state.messages:
    st.header("K-SEC Copilot에 오신 것을 환영합니다!")
    st.info("👈 왼쪽 사이드바에 분석할 YAML 파일을 업로드하여 보안 분석을 시작하세요.")
else:
    st.header("💬 분석 채팅")
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"], avatar="👤" if msg["role"] == "user" else "🛡️"):
            st.markdown(msg["content"])
    
    if prompt := st.chat_input("분석 결과에 대해 추가 질문을 입력하세요...", disabled=not st.session_state.analysis_complete):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)

        with st.chat_message("assistant", avatar="🛡️"):
            with st.spinner("답변을 생각하는 중..."):
                try:
                    chat_payload = {
                        "initial_analysis": st.session_state.initial_analysis_result,
                        "chat_history": st.session_state.messages[:-1],
                        "new_question": prompt
                    }
                    response = requests.post(BACKEND_CHAT_URL, json=chat_payload)
                    response.raise_for_status()
                    result_text = response.json().get("result", "답변을 받아오지 못했습니다.")
                    st.markdown(result_text)
                    st.session_state.messages.append({"role": "assistant", "content": result_text})
                except requests.exceptions.RequestException as e:
                    st.error(f"백엔드 서버와 통신 중 오류가 발생했습니다: {e}")

