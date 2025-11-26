"""
CLI helper to run the existing Ragnarok (prompt_template) pipeline on a directory
of Kubernetes YAML files and emit before/after YAMLs into a single output folder.

Usage:
    python ragnarok.py path/to/yaml_dir [-o OUTPUT_DIR] [--mode user|expert] [-q QUESTION]
"""

import argparse
import os
import re
import sys
import time
import threading
from pathlib import Path
from typing import Tuple, Optional

try:
    import psutil
except Exception:
    psutil = None

from rag_pipeline import prepare_analysis, generate_analysis_answer

# 기본 질문: Streamlit 프론트엔드의 기본 질문과 동일하게 맞춰둠
DEFAULT_QUESTION = "이 YAML 파일의 내용을 분석하고, 주요 설정과 잠재적인 보안 취약점에 대해 종합적으로 설명해 줘."

# prompt_template.md 출력 형식에 맞춘 코드 블록 추출 패턴
CODE_BLOCK_PATTERN = re.compile(r"```(?:yaml)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class ResourceMonitor:
    """백그라운드에서 시스템 리소스를 측정하는 모니터 클래스"""
    def __init__(self, interval: float = 0.1):
        self.interval = interval
        self.running = False
        self.thread = None
        self.cpu_values = []
        self.mem_values = []
        self.net_start = None
        self.net_end = None

    def start(self):
        """측정 시작"""
        self.running = True
        self.cpu_values = []
        self.mem_values = []
        if psutil:
            # CPU 측정 초기화 (첫 호출은 0.0이나 무의미한 값이므로 버림/초기화)
            psutil.cpu_percent(interval=None)
            self.net_start = psutil.net_io_counters()
        
        self.thread = threading.Thread(target=self._monitor_loop)
        self.thread.start()

    def stop(self):
        """측정 종료"""
        self.running = False
        if self.thread:
            self.thread.join()
        if psutil:
            self.net_end = psutil.net_io_counters()

    def _monitor_loop(self):
        while self.running:
            if psutil:
                # cpu_percent(interval=interval)은 해당 시간만큼 블로킹하며 평균을 냄
                cpu = psutil.cpu_percent(interval=self.interval)
                mem = psutil.Process().memory_info().rss
                self.cpu_values.append(cpu)
                self.mem_values.append(mem)
            else:
                time.sleep(self.interval)

    def get_metrics(self) -> dict:
        """
        수집된 데이터의 평균/누적 값을 반환합니다.
        - avg_cpu_percent: 평균 CPU 사용률 (%)
        - avg_memory_mb: 평균 메모리 사용량 (MB)
        - total_network_mb: 구간 내 총 네트워크 트래픽 (MB, Sent+Recv)
        """
        avg_cpu = 0.0
        avg_mem = 0.0
        net_mb = 0.0

        if self.cpu_values:
            avg_cpu = sum(self.cpu_values) / len(self.cpu_values)
        
        if self.mem_values:
            avg_mem = (sum(self.mem_values) / len(self.mem_values)) / (1024 * 1024)  # Bytes -> MB

        if psutil and self.net_start and self.net_end:
            sent = self.net_end.bytes_sent - self.net_start.bytes_sent
            recv = self.net_end.bytes_recv - self.net_start.bytes_recv
            net_mb = (sent + recv) / (1024 * 1024)  # Bytes -> MB

        return {
            "avg_cpu_percent": avg_cpu,
            "avg_memory_mb": avg_mem,
            "total_network_mb": net_mb
        }


def extract_yaml_blocks(text: str, fallback_before: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """
    prompt_template 출력에서 '수정 전/후' YAML 코드 블록을 추출합니다.
    - 2개 블록: before/after 둘 다 반환
    - 1개 블록: fallback_before가 있으면 (fallback_before, after)로 반환
    """
    matches = CODE_BLOCK_PATTERN.findall(text or "")
    if len(matches) >= 2:
        before = matches[0].strip()
        after = matches[1].strip()
        return before + "\n", after + "\n"

    if len(matches) == 1 and fallback_before is not None:
        after = matches[0].strip()
        return fallback_before.rstrip() + "\n", after + "\n"

    return None


def _read_net_dev_bytes() -> Optional[dict]:
    """psutil 미사용 시 /proc/net/dev에서 네트워크 누적 바이트를 읽어옵니다."""
    try:
        rx = tx = 0
        with open("/proc/net/dev", "r", encoding="utf-8") as f:
            lines = f.readlines()[2:]  # 헤더 2줄 제외
        for line in lines:
            parts = line.split()
            if len(parts) >= 10:
                rx += int(parts[1])
                tx += int(parts[9])
        return {"net_bytes_recv": rx, "net_bytes_sent": tx}
    except Exception:
        return None


def snapshot_resources() -> dict:
    """(기존 콘솔 출력용) CPU 시간, RSS, 네트워크 누적 바이트를 스냅샷으로 저장합니다."""
    data = {}
    try:
        if psutil:
            proc = psutil.Process()
            ct = proc.cpu_times()
            data["cpu_time_s"] = (ct.user or 0) + (ct.system or 0)
            mem = proc.memory_info()
            data["rss_bytes"] = getattr(mem, "rss", 0)
            net = psutil.net_io_counters()
            data["net_bytes_sent"] = getattr(net, "bytes_sent", 0)
            data["net_bytes_recv"] = getattr(net, "bytes_recv", 0)
        else:
            import resource

            ru = resource.getrusage(resource.RUSAGE_SELF)
            data["cpu_time_s"] = (ru.ru_utime or 0) + (ru.ru_stime or 0)
            data["rss_bytes"] = getattr(ru, "ru_maxrss", 0) * 1024  # kB → bytes (Linux)
            net = _read_net_dev_bytes()
            if net:
                data.update(net)
    except Exception:
        pass
    return data


def diff_resources(start: Optional[dict], end: Optional[dict]) -> dict:
    start = start or {}
    end = end or {}

    def delta(key: str):
        return (end.get(key) or 0) - (start.get(key) or 0)

    diff = {
        "cpu_time_s": delta("cpu_time_s"),
        "rss_bytes": end.get("rss_bytes", 0),
    }
    if "net_bytes_sent" in end and "net_bytes_sent" in start:
        diff["net_bytes_sent"] = delta("net_bytes_sent")
    if "net_bytes_recv" in end and "net_bytes_recv" in start:
        diff["net_bytes_recv"] = delta("net_bytes_recv")
    return diff


def format_bytes(num: float) -> str:
    step = 1024.0
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if abs(num) < step:
            return f"{num:.1f}{unit}"
        num /= step
    return f"{num:.1f}EB"


def format_metrics(metrics: Optional[dict]) -> str:
    if not metrics:
        return ""

    def stage_duration(stage_name: str) -> Optional[str]:
        stage = metrics.get(stage_name) or {}
        if "duration_s" in stage:
            return f"{stage_name[:4]} {stage['duration_s']:.2f}s"
        return None

    parts = []
    prep_d = stage_duration("prepare")
    gen_d = stage_duration("generation")
    if prep_d:
        parts.append(prep_d)
    if gen_d:
        parts.append(gen_d)

    cpu_total = sum((stage.get("cpu_time_s") or 0) for stage in metrics.values())
    if cpu_total:
        parts.append(f"cpu+{cpu_total:.2f}s")

    rss = next((stage["rss_bytes"] for stage in metrics.values() if stage.get("rss_bytes")), 0)
    if rss:
        parts.append(f"rss {format_bytes(rss)}")

    net_sent = sum((stage.get("net_bytes_sent") or 0) for stage in metrics.values())
    net_recv = sum((stage.get("net_bytes_recv") or 0) for stage in metrics.values())
    if net_sent or net_recv:
        parts.append(f"net +{format_bytes(net_sent + net_recv)}")

    return f" | {', '.join(parts)}" if parts else ""


def slug_from_path(path: Path, base_dir: Path) -> str:
    """입력 디렉터리 상대 경로를 출력 파일명으로 안전하게 변환합니다."""
    rel = path.relative_to(base_dir)
    parts = list(rel.parts)
    if rel.suffix:
        parts[-1] = rel.stem  # 확장자 제거
    return "__".join(parts)


def append_benchmark_log(output_dir: Path, filename: str, slug: str, value: str):
    """벤치마크 로그 파일에 한 줄을 추가합니다."""
    log_dir = output_dir / "ragnarok"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / filename
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{slug}]: {value}\n")
    except Exception as e:
        print(f"[WARN] Failed to write log {filename}: {e}")


def process_file(file_path: Path, base_dir: Path, output_dir: Path, question: str, mode: str) -> dict:
    """단일 YAML 파일을 분석하고 결과 YAML을 저장합니다."""
    result = {"file": str(file_path), "status": "ok", "details": ""}
    slug = slug_from_path(file_path, base_dir)
    metrics: dict = {}

    def _run_generation(prepared_data: dict, q: str, attempt: int = 0):
        """LLM 호출 + 코드블록 추출 (+ raw 저장)."""
        answer = generate_analysis_answer(prepared_data, q, mode=mode)
        if answer.get("error"):
            result.update({"status": "generate_error", "details": answer.get("error")})
            return None, None

        answer_text = answer.get("result") or answer.get("llm_full_response") or ""
        blocks = extract_yaml_blocks(answer_text, fallback_before=content)
        return blocks, answer_text

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        result.update({"status": "read_error", "details": str(e)})
        result["metrics"] = metrics
        return result

    # 1. 전처리 (Prepare)
    prep_res_start = snapshot_resources()
    prep_start = time.perf_counter()
    try:
        prep = prepare_analysis(content, mode=mode)
    except Exception as e:
        result.update({"status": "prepare_error", "details": str(e)})
        metrics["prepare"] = diff_resources(prep_res_start, snapshot_resources())
        metrics["prepare"]["duration_s"] = time.perf_counter() - prep_start
        result["metrics"] = metrics
        return result

    prep_res_end = snapshot_resources()
    metrics["prepare"] = diff_resources(prep_res_start, prep_res_end)
    metrics["prepare"]["duration_s"] = time.perf_counter() - prep_start

    if prep.get("error"):
        result.update({"status": "prepare_error", "details": prep.get("error")})
        result["metrics"] = metrics
        return result

    # 2. 후처리 (Post-processing) 시작
    # 전처리가 끝난 시점부터 측정을 시작합니다.
    monitor = ResourceMonitor()
    monitor.start()
    post_process_start = time.perf_counter()

    prepared_data = prep.get("prepared_data")
    llm_res_start = snapshot_resources() # 기존 로직 호환용

    if prepared_data is None:
        # 보안 이슈 없거나 사전 분석 실패 -> 원본을 그대로 저장
        result.update({"status": "ok_no_prepared_data", "details": "prepared_data is None; saving original as before/after"})
        before_after = (content, content)
    else:
        # 1차 시도
        blocks, answer_text = _run_generation(prepared_data, question, attempt=0)
        before_after = blocks
        last_answer_text = answer_text or ""

        # 2차 시도: before/after가 동일하면 강제 힌트 추가 후 한 번 더 시도
        if before_after and before_after[0].strip() == before_after[1].strip():
            hint = (
                "\n\n[재요청] 원본과 동일한 수정 후 YAML을 주지 말고, 보안 개선을 적용하세요. "
                "특히 cluster-admin, privileged, default 네임스페이스 사용 등 고권한 설정은 "
                "최소 권한(Role=viewer 등)으로 낮추고 메타데이터 이름도 변경하세요. "
                "수정 후 블록에는 변경사항이 반드시 반영돼야 합니다."
            )
            blocks_retry, _ = _run_generation(prepared_data, question + hint, attempt=1)
            last_answer_text = (_ or "") or last_answer_text
            if blocks_retry and blocks_retry[0].strip() != blocks_retry[1].strip():
                before_after = blocks_retry
            else:
                before_after = None

        # 파싱 실패 시 폴백: 원본 저장 + RAW 응답 저장
        if not before_after:
            raw_path = output_dir / f"{slug}.raw.txt"
            try:
                raw_path.write_text(last_answer_text, encoding="utf-8")
                raw_note = f" | raw saved to {raw_path}"
            except Exception as e:
                raw_note = f" | raw save failed: {e}"

            result.update({
                "status": "ok_raw_saved",
                "details": f"LLM response had no YAML code block; original YAML kept{raw_note}"
            })
            before_after = (content, content)

    # 결과 파일 쓰기
    after_path = output_dir / f"{slug}.after.yaml"
    try:
        after_path.write_text(before_after[1], encoding="utf-8")
        if not result["status"].startswith("ok"):
            result["status"] = "ok"
        result["details"] = f"{result.get('details', '')} | saved to {after_path}".strip()
    except Exception as e:
        result.update({"status": "write_error", "details": str(e)})

    # 기존 로직용 메트릭 종료
    llm_res_end = snapshot_resources()
    metrics["generation"] = diff_resources(llm_res_start, llm_res_end)
    metrics["generation"]["duration_s"] = time.perf_counter() - post_process_start  # 단순화를 위해 전체 시간 사용

    # 3. 후처리 (Post-processing) 종료 및 로그 기록
    monitor.stop()
    post_process_duration = time.perf_counter() - post_process_start
    res_stats = monitor.get_metrics()

    # 로그 파일 기록
    append_benchmark_log(output_dir, "ragnarok_benchmark_cpu_percent.log", slug, f"{res_stats['avg_cpu_percent']:.2f} %")
    append_benchmark_log(output_dir, "ragnarok_benchmark_memory.log", slug, f"{res_stats['avg_memory_mb']:.2f} MB")
    append_benchmark_log(output_dir, "ragnarok_benchmark_network.log", slug, f"{res_stats['total_network_mb']:.2f} MB")
    append_benchmark_log(output_dir, "ragnarok_benchmark_generation_time.log", slug, f"{post_process_duration:.4f} sec")

    result["metrics"] = metrics
    return result


def find_yaml_files(input_dir: Path) -> list[Path]:
    """입력 디렉터리 아래의 모든 .yaml/.yml 파일을 재귀적으로 찾습니다."""
    return sorted(
        [p for p in input_dir.rglob("*") if p.suffix.lower() in [".yaml", ".yml"] and p.is_file()]
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run Ragnarok prompt pipeline on a directory of YAML files and emit before/after YAMLs."
    )
    parser.add_argument("input_path", help="YAML 파일 또는 디렉터리 경로")
    parser.add_argument(
        "-o", "--output-dir", default="ragnarok_output", help="분석 결과(before/after)를 저장할 디렉터리 (기본: ragnarok_output)"
    )
    parser.add_argument("--mode", choices=["user", "expert"], default="user", help="LLM 프롬프트 모드 (기본: user/prompt_template.md)")
    parser.add_argument(
        "-q", "--question", default=DEFAULT_QUESTION, help="LLM에 전달할 질문 텍스트 (기본: Streamlit 기본 질문)"
    )
    args = parser.parse_args()

    input_path = Path(args.input_path).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

    if not input_path.exists():
        print(f"[ERROR] 입력 경로를 찾을 수 없습니다: {input_path}")
        sys.exit(1)

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[ERROR] 출력 디렉터리를 만들 수 없습니다: {output_dir} ({e})")
        sys.exit(1)

    if input_path.is_file():
        yaml_files = [input_path]
        base_dir = input_path.parent
    else:
        base_dir = input_path
        yaml_files = find_yaml_files(input_path)

    if not yaml_files:
        print(f"[ERROR] YAML(.yaml/.yml) 파일을 찾지 못했습니다: {input_path}")
        sys.exit(1)

    print(f"[INFO] 입력 경로: {input_path}")
    print(f"[INFO] 출력 디렉터리: {output_dir}")
    print(f"[INFO] 대상 파일 수: {len(yaml_files)}")
    print(f"[INFO] 모드: {args.mode} | 질문: {args.question}")
    print("-" * 60)

    summary = {"ok": 0, "failed": 0}
    for idx, file_path in enumerate(yaml_files, 1):
        print(f"[{idx}/{len(yaml_files)}] {file_path} ... ", end="", flush=True)
        res = process_file(file_path, base_dir, output_dir, args.question, args.mode)
        status = res["status"]
        metrics_note = format_metrics(res.get("metrics"))
        if status.startswith("ok"):
            summary["ok"] += 1
            print(f"OK ({status}){metrics_note}")
        else:
            summary["failed"] += 1
            print(f"FAIL ({status}){metrics_note}")
            if res.get("details"):
                print(f"        -> {res['details']}")

    print("-" * 60)
    print(f"[DONE] 완료: {summary['ok']}개 성공, {summary['failed']}개 실패")
    if summary["failed"]:
        print("       실패한 파일은 개별 로그 메시지를 확인하세요.")


if __name__ == "__main__":
    main()