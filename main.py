# main.py (메모리 관리 통합 버전 - API 정리)

import uuid
import asyncio
from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form
from pydantic import BaseModel

from dotenv import load_dotenv
from langsmith import traceable

from fastapi.middleware.cors import CORSMiddleware
from rag_pipeline import prepare_analysis, generate_analysis_answer, continue_chat

# 메모리 관리 함수 import
from db_handler_es import shutdown_handler

app = FastAPI()

load_dotenv()

# --- CORS 설정 ---
origins = ["http://localhost:8501"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 작업 결과를 저장할 임시 저장소 ---
job_results = {}

# --- API 요청/응답 모델 ---
class GenerateAnswerRequest(BaseModel):
    task_id: str
    question: str
    mode: str = "user"  # ⭐ 추가

class ChatRequest(BaseModel):
    initial_analysis: str
    chat_history: list
    new_question: str
    mode: str = "user"  # ⭐ 추가


# 서버 시작 이벤트
@app.on_event("startup")
async def startup_event():
    """서버 시작 시 실행"""
    pass


# 서버 종료 이벤트
@app.on_event("shutdown")
async def shutdown_event():
    """서버 종료 시 리소스 정리"""
    shutdown_handler()


# --- 백그라운드에서 실행될 실제 분석 함수 ---
@traceable(run_type="chain")
def run_prepare_in_background(task_id: str, yaml_content: str, mode: str = "user"):
    """[백그라운드] YAML 사전 분석만 수행하여 결과를 저장합니다."""
    print(f" -> [BackgroundTask] Prepare Task {task_id}: 사전 분석 시작... (mode={mode})")
    try:
        result = prepare_analysis(yaml_content, mode=mode)
        job_results[task_id] = {"status": "completed", "result": result, "mode": mode}
        print(f" -> [BackgroundTask] Prepare Task {task_id}: 사전 분석 완료.")
    except Exception as e:
        print(f" -> [BackgroundTask] Prepare Task {task_id}: 오류 발생 - {e}")
        job_results[task_id] = {"status": "error", "result": str(e), "mode": mode}


# --- API 엔드포인트들 ---
@app.post("/prepare-analysis")
async def prepare_analysis_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    mode: str = Form("user")
):
    """[1단계] 파일 업로드 시 즉시 호출되어 사전 분석을 백그라운드에서 시작합니다."""
    task_id = str(uuid.uuid4())
    yaml_content = (await file.read()).decode('utf-8')
    job_results[task_id] = {"status": "processing", "mode": mode}

    # 백그라운드 작업 실행 시 mode 전달
    background_tasks.add_task(run_prepare_in_background, task_id, yaml_content, mode)
    print(f" -> [FastAPI] /prepare-analysis: Task {task_id} 시작됨. (mode={mode})")

    return {"task_id": task_id, "mode": mode}


@app.post("/generate-answer")
async def generate_answer_endpoint(request: GenerateAnswerRequest):
    """[2단계] '분석 시작' 클릭 시 호출. 사전 분석이 끝나길 기다린 후 최종 답변을 생성합니다."""
    task_id = request.task_id
    question = request.question
    mode = request.mode  # ⭐ 요청에서 직접 받은 mode 사용!
    print(f" -> [FastAPI] /generate-answer: Task {task_id}의 최종 답변 요청 수신. (mode={mode})")

    # 사전 분석이 완료될 때까지 최대 90초간 기다립니다.
    for _ in range(90):
        if job_results.get(task_id, {}).get("status") in ["completed", "error"]:
            break
        await asyncio.sleep(1)

    prepare_job = job_results.get(task_id)
    if not prepare_job or prepare_job["status"] != "completed":
        return {"error": "사전 분석에 실패했거나 시간이 너무 오래 걸립니다."}
    
    prepare_result = prepare_job["result"]
    prepared_data = prepare_result.get("prepared_data")

    if prepared_data is None:
        return {"result": "Trivy 스캔 결과, 보안 문제점이 발견되지 않았습니다."}

    # ⭐ 최종 답변 생성 시 요청의 mode 사용
    return generate_analysis_answer(prepared_data, question, mode=mode)


@app.post("/chat")
async def handle_chat(request: ChatRequest):
    """후속 질문을 처리합니다."""
    # ⭐ mode 파라미터 전달
    return continue_chat(
        request.initial_analysis, 
        request.chat_history, 
        request.new_question,
        mode=request.mode
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)