import streamlit as st
import requests
import time
from concurrent.futures import ThreadPoolExecutor

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
if "selected_mode" not in st.session_state:
    st.session_state.selected_mode = "user"


# --- 로직 함수 (백엔드 요청) ---
def perform_analysis_request(task_id, question, mode):
    """백엔드에 분석을 요청하는 블로킹 호출"""
    start_req_time = time.time()
    try:
        payload = {"task_id": task_id, "question": question, "mode": mode}  # ⭐ mode 추가
        response = requests.post(BACKEND_GENERATE_URL, json=payload, timeout=300)
        response.raise_for_status()
        result_data = response.json()
        end_req_time = time.time()
        elapsed_time = end_req_time - start_req_time
        return result_data, elapsed_time
    except requests.exceptions.RequestException as e:
        return {"error": f"백엔드 서버와 통신 중 오류가 발생했습니다: {e}"}, 0

def perform_chat_request(chat_payload):
    """백엔드에 챗 응답을 요청하는 블로킹 호출"""
    start_req_time = time.time()
    try:
        response = requests.post(BACKEND_CHAT_URL, json=chat_payload, timeout=300)
        response.raise_for_status()
        result_text = response.json().get("result", "답변을 받아오지 못했습니다.")
        end_req_time = time.time()
        elapsed_time = end_req_time - start_req_time
        return result_text, elapsed_time
    except requests.exceptions.RequestException as e:
        return f"백엔드 서버와 통신 중 오류가 발생했습니다: {e}", 0

def handle_file_upload():
    """파일 업로더의 on_change 콜백. 백엔드에 사전 분석을 요청합니다."""
    if st.session_state.file_uploader_key:
        uploaded_file = st.session_state.file_uploader_key
        try:
            if st.session_state.analysis_task_id is None:
                st.info("파일을 수신했습니다. 백그라운드에서 분석을 준비합니다...")
                files = {'file': (uploaded_file.name, uploaded_file.getvalue(), 'application/x-yaml')}
                data = {
                    'mode': st.session_state.get('selected_mode', 'user')
                }

                response = requests.post(
                    BACKEND_PREPARE_URL,
                    files=files,
                    data=data,
                    timeout=60
                )
                response.raise_for_status()
                task_id = response.json().get("task_id")
                st.session_state.analysis_task_id = task_id
                st.session_state.analysis_mode = data['mode']
        except requests.exceptions.RequestException as e:
            st.error(f"파일 준비 중 오류가 발생했습니다: {e}")
            st.session_state.analysis_task_id = None

# --- 사이드바 UI ---
with st.sidebar:
    st.title("🛡️ K-SEC Copilot")
    st.markdown("---")

    if st.session_state.analysis_complete:
        # ⭐ 분석 완료 시 사용된 모드 표시
        completed_mode = st.session_state.get("analysis_mode", "user")
        mode_name = "전문가 모드" if completed_mode == "expert" else "일반 사용자 모드"
        st.success(f"✅ {mode_name}로 분석이 완료되었습니다.")
        
        if st.button("🔄️ 새 분석 시작하기", use_container_width=True):
            keys_to_delete = list(st.session_state.keys())
            for key in keys_to_delete:
                del st.session_state[key]
            st.rerun()
    
    st.header("1. 분석 설정")

    # 모드 선택 토글
    mode_label = "분석 모드 선택"
    new_mode = st.radio(
        label=mode_label,
        options=["user", "expert"],
        index=0 if st.session_state.get("selected_mode", "user") == "user" else 1,
        format_func=lambda x: "일반 사용자 모드" if x == "user" else "전문가 모드",
        help="일반 모드는 보고서 중심, 전문가 모드는 Diff 기반 상세 분석을 제공합니다.",
        disabled=st.session_state.analysis_complete
    )
    
    st.session_state.selected_mode = new_mode
    
    # 모드별 설명
    if st.session_state.selected_mode == "expert":
        st.info("""
        🔧 **전문가 모드**
        - Diff 형식의 상세 코드 수정안 제공
        - 보안 영향 분석 포함
        - 기술적 깊이 중심
        """)
    else:
        st.info("""
        📊 **일반 사용자 모드**
        - 이해하기 쉬운 보고서 형식
        - 위험도별 요약 제공
        - 친절한 설명 중심
        """)

    uploaded_file = st.file_uploader(
        "분석할 쿠버네티스 YAML 파일을 업로드하세요.",
        type=["yaml", "yml"],
        disabled=st.session_state.analysis_complete,
        on_change=handle_file_upload,
        key='file_uploader_key'
    )
    
    default_question = "이 YAML 파일의 내용을 분석하고, 주요 설정과 잠재적인 보안 취약점에 대해 종합적으로 설명해 줘."
    question = st.text_area(
        label="분석 요청 또는 질문:",
        value=default_question,
        disabled=st.session_state.analysis_complete,
        label_visibility="visible"
    )

    # Text Area 자동 높이 조절을 위한 JS
    auto_resize_script = """
    <script>
    const tx = parent.document.querySelector('textarea[aria-label="분석 요청 또는 질문:"]');
    if (tx) {
        function autoResize() {
            tx.style.height = 'auto';
            tx.style.height = (tx.scrollHeight) + 'px';
        }
        tx.addEventListener("input", autoResize, false);
        setTimeout(autoResize, 200);
    }
    </script>
    """
    st.components.v1.html(auto_resize_script, height=0)


    if st.button("🚀 분석 시작!", type="primary", use_container_width=True, disabled=st.session_state.analysis_complete):
        if st.session_state.analysis_task_id and question:
            # ⭐ 현재 모드 표시 및 저장
            current_mode = st.session_state.get("selected_mode", "user")
            st.session_state.analysis_mode = current_mode  # ← 최신 모드 저장!
            mode_name = "전문가 모드" if current_mode == "expert" else "일반 사용자 모드"
            st.info(f"🔍 {mode_name}로 분석을 시작합니다...")
            
            progress_placeholder = st.empty()
            start_time = time.time()
            
            analysis_steps = [
                "YAML 유효성 검사 및 구문 분석",
                "컨테이너 취약점 분석",
                "보안 벤치마크 및 가이드라인 검색 (RAG)",
                "사전 분석 결과 취합",
                "LLM을 통한 종합 보안 보고서 생성",
                "최종 보고서 포맷팅 및 완료"
            ]
            
            with ThreadPoolExecutor() as executor:
                future = executor.submit(perform_analysis_request, st.session_state.analysis_task_id, question, current_mode)
                
                total_duration_estimate = 30
                step_duration = total_duration_estimate / len(analysis_steps)

                with st.spinner("전문가가 최종 분석 보고서를 작성 중입니다..."):
                    while not future.done():
                        elapsed = time.time() - start_time
                        current_step_index = min(int(elapsed / step_duration), len(analysis_steps) - 1)
                        
                        progress_message = f"""
                        <div style="font-size: 1rem; color: #333; line-height: 1.6;">
                            <div>⏳ **분석 진행 중...** (경과 시간: <b>{elapsed:.1f}초</b>)</div>
                            <div style="margin-top: 8px;">⚙️ 현재 단계: <strong>{analysis_steps[current_step_index]}...</strong></div>
                        </div>
                        """
                        progress_placeholder.markdown(progress_message, unsafe_allow_html=True)
                        time.sleep(0.1)
                
                progress_placeholder.empty()
                result_data, elapsed_time = future.result()

                if "error" in result_data:
                    st.error(result_data["error"])
                else:
                    st.session_state.analysis_complete = True
                    raw_result = result_data.get("result", "")
                    st.session_state.initial_analysis_result = raw_result
                    
                    formatted_report = (
                        f"### 🛡️ 초기 분석 보고서\n\n"
                        f"{raw_result}\n\n"
                        f"---\n"
                        f"_*분석 소요 시간: **{elapsed_time:.2f}초**_"
                    )
                    st.session_state.messages = [
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": formatted_report}
                    ]
                    st.rerun()
        else:
            st.warning("먼저 YAML 파일을 업로드하고 질문을 입력해주세요.")

# --- 메인 화면 UI ---
if not st.session_state.messages:
    st.header("🛡️ K-SEC Copilot에 오신 것을 환영합니다!")
    st.markdown("쿠버네티스 보안 분석, 이제 전문가에게 맡기세요.")
    with st.container(border=True):
        st.markdown("""
        #### **🚀 시작 가이드**
        1.  👈 **왼쪽 사이드바**에 분석할 `YAML` 파일을 업로드하세요.
        2.  📝 기본 분석 요청을 확인하거나 직접 질문을 수정하세요.
        3.  🚀 **분석 시작!** 버튼을 눌러 종합 보안 분석 보고서를 받아보세요.
        4.  💬 분석 완료 후, 채팅을 통해 궁금한 점을 추가로 질문할 수 있습니다.
        """)
    st.info("보안 분석을 시작하려면 왼쪽 사이드바에서 파일을 업로드하세요.")
else:
    st.header("💬 분석 채팅")
    
    chat_container = st.container(height=600)
    for msg in st.session_state.messages:
        with chat_container.chat_message(msg["role"], avatar="👤" if msg["role"] == "user" else "🛡️"):
            st.markdown(msg["content"], unsafe_allow_html=True)
            # 어시스턴트의 답변 중 time 키가 있는 경우(후속 채팅)에만 소요 시간을 별도로 표시
            if msg.get("role") == "assistant" and "time" in msg:
                st.markdown(f"_*<small>답변 소요 시간: {msg['time']:.2f}초</small>*_", unsafe_allow_html=True)


    if st.session_state.messages and st.session_state.messages[-1]["role"] != "user":
        if prompt := st.chat_input("분석 결과에 대해 추가 질문을 입력하세요...", disabled=not st.session_state.analysis_complete):
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.rerun()

    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        user_prompt = st.session_state.messages[-1]["content"]
        
        with st.chat_message("assistant", avatar="🛡️"):
            message_container = st.empty()
            start_time = time.time()
            
            # 백엔드로 보낼 채팅 기록에서 time 같은 추가 정보를 제외하고 순수 대화 내용만 추출
            history_for_payload = [
                {"role": m["role"], "content": m["content"]} for m in st.session_state.messages[:-1]
            ]

            # ⭐ 채팅 요청에 mode 추가
            chat_payload = {
                "initial_analysis": st.session_state.initial_analysis_result,
                "chat_history": history_for_payload,
                "new_question": user_prompt,
                "mode": st.session_state.get("analysis_mode", "user")  # ⭐ 추가
            }

            with ThreadPoolExecutor() as executor:
                future = executor.submit(perform_chat_request, chat_payload)
                
                while not future.done():
                    elapsed = time.time() - start_time
                    message_container.markdown(f"**답변 생성 중...** ⏱️ `{elapsed:.1f}`초")
                    time.sleep(0.1)
                
                result_text, elapsed_time = future.result()

                # 답변 내용과 소요 시간을 UI에 임시로 함께 표시
                display_content = (
                    f"{result_text}\n\n"
                    f"_*<small>답변 소요 시간: {elapsed_time:.2f}초</small>*_"
                )
                message_container.markdown(display_content, unsafe_allow_html=True)
                
                # 세션 상태에는 답변 내용과 소요 시간을 분리하여 저장
                st.session_state.messages.append({
                    "role": "assistant", 
                    "content": result_text,
                    "time": elapsed_time
                })

                if 'response_sent' not in st.session_state or not st.session_state.response_sent:
                    st.session_state.response_sent = True
                    st.rerun()
    else:
        st.session_state.response_sent = False