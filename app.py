import streamlit as st
import requests
import time
import re  # <--- [필수] 정규식 import
from concurrent.futures import ThreadPoolExecutor

# --- 페이지 설정 ---
st.set_page_config(
    page_title="K-SEC Copilot",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 백엔드 서버 주소 ---
# (사용자님의 포트 번호에 맞게 수정하세요. 예: 8000 또는 8001)
BACKEND_PREPARE_URL = "http://127.0.0.1:8000/prepare-analysis"
BACKEND_GENERATE_URL = "http://127.0.0.1:8000/generate-answer"
BACKEND_CHAT_URL = "http://127.0.0.1:8000/chat"
BACKEND_APPLY_PATCH_URL = "http://127.0.0.1:8000/apply-patch"

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
    start_req_time = time.time()
    try:
        payload = {"task_id": task_id, "question": question, "mode": mode}
        response = requests.post(BACKEND_GENERATE_URL, json=payload, timeout=300)
        response.raise_for_status()
        result_data = response.json()
        end_req_time = time.time()
        elapsed_time = end_req_time - start_req_time
        return result_data, elapsed_time
    except requests.exceptions.RequestException as e:
        return {"error": f"백엔드 서버와 통신 중 오류가 발생했습니다: {e}"}, 0

def perform_chat_request(chat_payload):
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

def perform_apply_patch(original_yaml: str, selected_suggestions: list) -> dict:
    try:
        payload = {
            "original_yaml": original_yaml,
            "selected_suggestions": selected_suggestions
        }
        response = requests.post(BACKEND_APPLY_PATCH_URL, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"패치 적용 중 오류가 발생했습니다: {e}"}

def handle_file_upload():
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
        completed_mode = st.session_state.get("analysis_mode", "user")
        mode_name = "전문가 모드" if completed_mode == "expert" else "일반 사용자 모드"
        st.success(f"✅ {mode_name}로 분석이 완료되었습니다.")
        
        if st.button("🔄️ 새 분석 시작하기", use_container_width=True):
            keys_to_delete = [
                "line_suggestions", "review_index", "yaml_history", 
                "current_yaml_content", "analysis_complete", "analysis_task_id",
                "messages", "initial_analysis_result", "llm_full_response"
            ]
            for key in keys_to_delete:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
    
    st.header("1. 분석 설정")
    mode_label = "분석 모드 선택"
    new_mode = st.radio(
        label=mode_label,
        options=["user", "expert"],
        index=0 if st.session_state.get("selected_mode", "user") == "user" else 1,
        format_func=lambda x: "일반 사용자 모드" if x == "user" else "전문가 모드",
        help="일반 모드는 보고서 중심, 전문가 모드는 Hunk 단위 상세 분석을 제공합니다.",
        disabled=st.session_state.analysis_complete
    )
    st.session_state.selected_mode = new_mode
    if st.session_state.selected_mode == "expert":
        st.info("""
        🔧 **전문가 모드**
        - Hunk 단위의 대화형 수정안 제공
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
    auto_resize_script = """
    <script>
    const textareas = window.parent.document.querySelectorAll('textarea');
    textareas.forEach(textarea => {
        textarea.style.height = 'auto';
        textarea.style.height = textarea.scrollHeight + 'px';
    });
    </script>
    """
    st.components.v1.html(auto_resize_script, height=0)

    # --- 분석 시작 버튼 ---
    if st.button("🚀 분석 시작!", type="primary", use_container_width=True, disabled=st.session_state.analysis_complete):
        if st.session_state.analysis_task_id and question:
            current_mode = st.session_state.get("selected_mode", "user")
            st.session_state.analysis_mode = current_mode
            mode_name = "전문가 모드" if current_mode == "expert" else "일반 사용자 모드"
            st.info(f"🔍 {mode_name}로 분석을 시작합니다...")
            
            progress_placeholder = st.empty()
            start_time = time.time()
            analysis_steps = [
                "YAML 유효성 검사 및 구문 분석", "컨테이너 취약점 분석", "보안 벤치마크 및 가이드라인 검색 (RAG)",
                "사전 분석 결과 취합", "LLM 종합 보고서 생성", "최종 보고서 포맷팅 및 완료"
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
                    
                    if st.session_state.get("analysis_mode") == "expert" and "line_suggestions" in result_data:
                        st.session_state.line_suggestions = result_data["line_suggestions"]
                        st.session_state.original_yaml = result_data["original_yaml"]
                        st.session_state.llm_full_response = result_data.get("llm_full_response", "")
                        st.rerun()
                    
                    else:
                        raw_result = result_data.get("result", None)
                        if raw_result is None:
                            raw_result = result_data.get("llm_full_response", "분석 결과를 받았으나, 일반 모드 포맷이 아닙니다.")
                        st.session_state.initial_analysis_result = raw_result
                        formatted_report = (
                            f"### 🛡️ 초기 분석 보고서\n\n{raw_result}\n\n"
                            f"---\n_*분석 소요 시간: **{elapsed_time:.2f}초**_"
                        )
                        st.session_state.messages = [
                            {"role": "user", "content": question},
                            {"role": "assistant", "content": formatted_report}
                        ]
                        st.rerun()
        else:
            st.warning("먼저 YAML 파일을 업로드하고 질문을 입력해주세요.")

# --- 전문가 모드: '되돌아가기' 로직 적용 ---
if "line_suggestions" in st.session_state:
    st.header("전문가 모드: 보안 패치 검토")

    if "review_index" not in st.session_state:
        st.session_state.review_index = 0
    if "yaml_history" not in st.session_state:
        st.session_state.yaml_history = [st.session_state.original_yaml]

    suggestions = st.session_state.line_suggestions
    total_suggestions = len(suggestions)
    current_idx = st.session_state.review_index
    current_yaml_content = st.session_state.yaml_history[-1]

    # --- [상태 A] 검토할 항목이 남아있는 경우 ---
    if current_idx < total_suggestions:
        current_sug = suggestions[current_idx]
        progress = (current_idx / total_suggestions)
        st.progress(progress, text=f"보안 이슈 검토 중 ({current_idx + 1}/{total_suggestions})")

        col_left, col_right = st.columns([1.2, 1])

        # [좌측 패널]
        with col_left:
            st.subheader(f"📄 YAML 미리보기 (v{current_idx})")
            
            display_yaml = current_yaml_content
            lines = display_yaml.splitlines()
            highlight_line_number = -1
            target_line_content = ""
            
            # --- 계층적 검색 로직 ---
            try:
                path = current_sug.get('path', '')
                path_keys = path.split('.')
                
                current_search_line = 0
                
                for key in path_keys:
                    if key.isdigit():
                        continue
                    
                    key_regex = re.compile(r"^\s*" + re.escape(key) + r":")
                    
                    found_in_block = False
                    for i in range(current_search_line, len(lines)):
                        line = lines[i]
                        if key_regex.search(line):
                            current_search_line = i + 1
                            highlight_line_number = i
                            target_line_content = line.strip()
                            found_in_block = True
                            break
                    
                    if not found_in_block:
                        break
                
                if highlight_line_number != -1:
                    lines[highlight_line_number] = f"👉 {lines[highlight_line_number]}"
                    display_yaml = "\n".join(lines)
                    highlight_line_number += 1
                        
            except Exception as e:
                pass
            
            sug_type = current_sug.get('type')
            if highlight_line_number != -1:
                if sug_type == "추가":
                    st.info(f"👉 **`{highlight_line_number}`번 줄**의 `{target_line_content}` 내부에 새 항목을 **추가**합니다.")
                elif sug_type == "삭제":
                    st.warning(f"👉 **`{highlight_line_number}`번 줄**의 `{target_line_content}` 항목을 **삭제**합니다.")
                else:
                    st.info(f"👉 **`{highlight_line_number}`번 줄**의 `{target_line_content}` 항목을 **수정**합니다.")
            else:
                st.error(f"⚠️ **경로 탐색 실패!**")
                st.warning(f"경로 `{current_sug.get('path', '항목')}`를 찾을 수 없습니다. 이전 수정안이 이 코드를 삭제했을 수 있습니다.")

            st.code(display_yaml, language="yaml", line_numbers=True)

        # [우측 패널]
        with col_right:
            with st.container(border=True):
                st.subheader(f"🔴 이슈 {current_idx + 1}: {current_sug.get('type', '수정')}")
                st.caption(f"**경로:** `{current_sug.get('path')}`")
                st.markdown(f"**📝 진단 및 사유:**\n\n{current_sug.get('reason')}")
                st.divider()
                st.markdown("**🛠️ 수정 제안:**")
                
                # Diff 로직
                orig_val = current_sug.get('original_value', '')
                new_val = current_sug.get('proposed_value', '')
                diff_html = []
                if current_sug.get('type') == "삭제":
                    for line in orig_val.splitlines(): 
                        diff_html.append(f'<span style="color: #d32f2f; background-color: #ffebee;">- {line}</span>')
                elif current_sug.get('type') == "추가":
                    for line in new_val.splitlines(): 
                        diff_html.append(f'<span style="color: #388e3c; background-color: #e8f5e9;">+ {line}</span>')
                else:
                    diff_html.append(f'<span>path: {current_sug.get("path")}</span>')
                    for line in orig_val.splitlines(): 
                        diff_html.append(f'<span style="color: #d32f2f; background-color: #ffebee;">- {line}</span>')
                    for line in new_val.splitlines(): 
                        diff_html.append(f'<span style="color: #388e3c; background-color: #e8f5e9;">+ {line}</span>')
                st.markdown(
                    f'<div style="font-family: \'Fira Code\', \'Consolas\', monospace; white-space: pre; background-color: #fafafa; padding: 10px; border-radius: 5px; border: 1px solid #eee;">'
                    f"{'<br>'.join(diff_html)}"
                    f'</div>', 
                    unsafe_allow_html=True
                )
                
                st.warning("이 수정 사항을 적용하시겠습니까?")

                btn_col1, btn_col2, btn_col3 = st.columns([1.2, 1, 1])
                
                if btn_col1.button("✅ 수락 (적용)", key=f"accept_{current_idx}", type="primary", use_container_width=True):
                    with st.spinner("패치 적용 중..."):
                        patch_response = perform_apply_patch(
                            current_yaml_content,
                            [current_sug]
                        )
                        if "final_yaml" in patch_response:
                            st.session_state.yaml_history.append(patch_response["final_yaml"])
                            st.session_state.review_index += 1
                            st.success("적용되었습니다!")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error(f"적용 실패: {patch_response.get('error')}")

                if btn_col2.button("❌ 거절 (건너뛰기)", key=f"reject_{current_idx}", use_container_width=True):
                    st.session_state.yaml_history.append(current_yaml_content)
                    st.session_state.review_index += 1
                    st.info("건너뜁니다.")
                    time.sleep(0.5)
                    st.rerun()
                
                with btn_col3:
                    if st.button("↩️ 되돌아가기", key=f"back_{current_idx}", use_container_width=True, disabled=(current_idx == 0)):
                        st.session_state.review_index -= 1
                        st.session_state.yaml_history.pop()
                        st.warning("이전 단계로 되돌아갑니다.")
                        time.sleep(0.5)
                        st.rerun()

    # --- [상태 B] 모든 검토 완료 ---
    else:
        st.success("모든 보안 이슈에 대한 검토가 완료되었습니다!")
        st.progress(1.0, text="검토 완료")
        st.divider()
        st.subheader("최종 수정 코드")
        
        final_yaml = st.session_state.yaml_history[-1]
        st.code(final_yaml, language="yaml")

        col_dn1, col_dn2 = st.columns(2)
        with col_dn1:
            st.download_button(
                label="💾 최종 YAML 다운로드",
                data=final_yaml,
                file_name="ksec_patched_final.yaml",
                mime="application/x-yaml",
                type="primary",
                use_container_width=True
            )
        with col_dn2:
            if st.button("🔄 처음부터 다시 분석하기", use_container_width=True):
                keys_to_delete = [
                    "line_suggestions", "review_index", "yaml_history", 
                    "current_yaml_content", "analysis_complete", "analysis_task_id",
                    "messages", "initial_analysis_result", "llm_full_response"
                ]
                for k in keys_to_delete:
                    if k in st.session_state:
                        del st.session_state[k]
                st.rerun()
        
        # ✅ [핵심 수정] 최종 패치 요약 생성
        st.divider()
        st.header("💬 분석 채팅")
        
        # 적용된 패치 요약 생성
        accepted_patches = []
        for i, sug in enumerate(st.session_state.line_suggestions):
            # review_index까지 진행했고, yaml_history가 더 길면 해당 패치가 적용된 것
            if i < st.session_state.review_index:
                # yaml_history[i]와 yaml_history[i+1]이 다르면 적용된 것
                if i + 1 < len(st.session_state.yaml_history):
                    if st.session_state.yaml_history[i] != st.session_state.yaml_history[i + 1]:
                        accepted_patches.append({
                            "index": i + 1,
                            "type": sug.get("type"),
                            "path": sug.get("path"),
                            "reason": sug.get("reason")
                        })
        
        # 초기 분석 결과에 최종 YAML과 패치 요약 포함
        patch_summary = "### 적용된 보안 패치 요약\n\n"
        if accepted_patches:
            for patch in accepted_patches:
                patch_summary += f"**{patch['index']}. [{patch['type']}] {patch['path']}**\n"
                patch_summary += f"- 사유: {patch['reason']}\n\n"
        else:
            patch_summary += "모든 제안을 거절했습니다.\n\n"
        
        patch_summary += f"### 최종 YAML 파일\n\n```yaml\n{final_yaml}\n```\n\n"
        
        # LLM 원본 분석 결과 추가
        original_analysis = st.session_state.get("llm_full_response", "")
        
        # initial_analysis_result 업데이트
        st.session_state.initial_analysis_result = (
            f"## 전문가 모드 보안 분석 완료\n\n"
            f"{patch_summary}\n\n"
            f"---\n\n"
            f"### 원본 분석 결과\n\n{original_analysis}"
        )
        
        # 메시지 히스토리 초기화
        if "messages" not in st.session_state or len(st.session_state.messages) == 0:
            st.session_state.messages = [
                {"role": "assistant", "content": (
                    f"모든 패치 검토가 완료되었습니다! 🎉\n\n"
                    f"**적용된 패치: {len(accepted_patches)}개**\n"
                    f"**거절된 패치: {len(st.session_state.line_suggestions) - len(accepted_patches)}개**\n\n"
                    f"최종 YAML 파일이나 적용된 보안 패치에 대해 궁금한 점이 있으시면 질문해주세요!"
                )}
            ]
        
        # 채팅 메시지 표시
        chat_container = st.container(height=400)
        for msg in st.session_state.messages:
            with chat_container.chat_message(msg["role"], avatar="👤" if msg["role"] == "user" else "🛡️"):
                st.markdown(msg["content"], unsafe_allow_html=True)
                if msg.get("role") == "assistant" and "time" in msg:
                    st.markdown(f"_*<small>답변 소요 시간: {msg['time']:.2f}초</small>*_", unsafe_allow_html=True)

        # 채팅 입력
        if st.session_state.messages[-1]["role"] != "user":
            if prompt := st.chat_input("패치 결과에 대해 추가 질문을 입력하세요..."):
                st.session_state.messages.append({"role": "user", "content": prompt})
                st.rerun()

        # 사용자 메시지에 대한 응답 생성
        if st.session_state.messages[-1]["role"] == "user":
            user_prompt = st.session_state.messages[-1]["content"]
            
            with st.chat_message("assistant", avatar="🛡️"):
                message_container = st.empty()
                start_time = time.time()
                history_for_payload = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages[:-1]]
                chat_payload = {
                    "initial_analysis": st.session_state.initial_analysis_result,  # ✅ 최종 YAML 포함
                    "chat_history": history_for_payload,
                    "new_question": user_prompt,
                    "mode": st.session_state.get("analysis_mode", "expert")
                }
                with ThreadPoolExecutor() as executor:
                    future = executor.submit(perform_chat_request, chat_payload)
                    while not future.done():
                        elapsed = time.time() - start_time
                        message_container.markdown(f"**답변 생성 중...** ⏱️ `{elapsed:.1f}`초")
                        time.sleep(0.1)
                    result_text, elapsed_time = future.result()
                    display_content = f"{result_text}\n\n_*<small>답변 소요 시간: {elapsed_time:.2f}초</small>*_"
                    message_container.markdown(display_content, unsafe_allow_html=True)
                    st.session_state.messages.append({"role": "assistant", "content": result_text, "time": elapsed_time})
                    st.rerun()

# --- [수정] 일반 모드 채팅 로직 (전문가 모드와 분리) ---
elif "messages" in st.session_state and len(st.session_state.messages) > 0 and "line_suggestions" not in st.session_state:
    st.header("💬 분석 채팅")
    
    chat_container = st.container(height=800)
    for msg in st.session_state.messages:
        with chat_container.chat_message(msg["role"], avatar="👤" if msg["role"] == "user" else "🛡️"):
            st.markdown(msg["content"], unsafe_allow_html=True)
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
            history_for_payload = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages[:-1]]
            chat_payload = {
                "initial_analysis": st.session_state.initial_analysis_result,
                "chat_history": history_for_payload,
                "new_question": user_prompt,
                "mode": st.session_state.get("analysis_mode", "user")
            }
            with ThreadPoolExecutor() as executor:
                future = executor.submit(perform_chat_request, chat_payload)
                while not future.done():
                    elapsed = time.time() - start_time
                    message_container.markdown(f"**답변 생성 중...** ⏱️ `{elapsed:.1f}`초")
                    time.sleep(0.1)
                result_text, elapsed_time = future.result()
                display_content = f"{result_text}\n\n_*<small>답변 소요 시간: {elapsed_time:.2f}초</small>*_"
                message_container.markdown(display_content, unsafe_allow_html=True)
                st.session_state.messages.append({"role": "assistant", "content": result_text, "time": elapsed_time})
                if 'response_sent' not in st.session_state or not st.session_state.response_sent:
                    st.session_state.response_sent = True
                    st.rerun()
    else:
        st.session_state.response_sent = False

# --- 시작 가이드 ---
elif "line_suggestions" not in st.session_state:
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