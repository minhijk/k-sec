#kubescape scan framework nsa vulnerable/case-001.yaml --verbose
import subprocess
import os
from pathlib import Path
import sys
import time
import psutil
import tempfile
import shutil # [추가] 명령어 존재 확인용

# --- 설정 ---

# Kubescape는 보통 환경변수(PATH)에 등록되므로 명령어만 있으면 됩니다.
# 만약 실행이 안 된다면 전체 경로(예: C:\Users\...\kubescape.exe)를 적어주세요.
KUBESCAPE_CMD = "kubescape" 

TARGET_DIRECTORIES = [Path("vulnerable"), Path("secure")]
LOG_DIR = Path("kubescape") # 로그 폴더 이름 변경

BENCH_LOGS = {
    "time": LOG_DIR / "kubescape_benchmark_time.log",
    "cpu": LOG_DIR / "kubescape_benchmark_cpu.log",
    "memory": LOG_DIR / "kubescape_benchmark_memory.log",
    "network": LOG_DIR / "kubescape_benchmark_network.log"
}

RESULTS_SUFFIX = "_kubescape_results.log"

# --- --- ---

def run_scans_and_monitor():
    print("Kubescape 성능 분석(CPU, Mem, Network, Time)을 시작합니다...")
    
    # Kubescape 설치 여부 확인
    if shutil.which(KUBESCAPE_CMD) is None:
        print(f"🚨 [FATAL] '{KUBESCAPE_CMD}' 명령어를 찾을 수 없습니다. 설치가 되었는지, PATH에 등록되었는지 확인해주세요.")
        sys.exit(1)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        print(f"📂 Logs Directory: {LOG_DIR.resolve()}")
    except Exception as e:
        print(f"🚨 [Fatal] 로그 폴더 생성 실패: {e}")
        sys.exit(1)
        
    print("-" * 60)

    try:
        files_handle = {}
        for key, filepath in BENCH_LOGS.items():
            f = open(filepath, 'w', encoding='utf-8')
            f.write(f"--- Kubescape Benchmark: {key.upper()} ---\n")
            files_handle[key] = f

        total_files_scanned = 0
        
        for dir_path in TARGET_DIRECTORIES:
            results_log_path = LOG_DIR / f"{dir_path.name}{RESULTS_SUFFIX}"
            print(f"\nProcessing Directory: {dir_path.resolve()}")
            
            for f in files_handle.values():
                f.write(f"\n--- Directory: {dir_path.name} ---\n")

            if not dir_path.is_dir():
                print(f"🚨 [Error] 디렉터리 없음: {dir_path}")
                continue

            # Checkov와 동일하게 case-*.yaml 파일 검색
            yaml_files = sorted(dir_path.glob("case-*.yaml"))
            if not yaml_files:
                print(f"🚨 [Warning] '{dir_path}'에 case-*.yaml 파일이 없습니다.")
                continue

            with open(results_log_path, 'w', encoding='utf-8') as results_file:
                results_file.write(f"--- Kubescape Scan Results for: {dir_path.name} ---\n")

                for yaml_file in yaml_files:
                    # [변경점] Kubescape 명령어 구성
                    # framework nsa: NSA 기준 스캔 (비교를 위한 표준)
                    # --verbose: 통과한 항목도 보기 위해 사용 (필요 없으면 제거 가능)
                    command = [KUBESCAPE_CMD, "scan", "framework", "nsa", str(yaml_file)]
                    
                    print(f"  > Scanning {yaml_file.name} ", end="", flush=True)

                    try:
                        start_time = time.perf_counter()
                        net_io_start = psutil.net_io_counters()
                        
                        # PIPE 대신 임시 파일을 사용하여 데드락 방지 (Checkov 코드와 동일)
                        with tempfile.TemporaryFile() as temp_stdout, tempfile.TemporaryFile() as temp_stderr:
                            
                            process = subprocess.Popen(
                                command,
                                stdout=temp_stdout,
                                stderr=temp_stderr
                            )

                            try:
                                ps_proc = psutil.Process(process.pid)
                            except psutil.NoSuchProcess:
                                ps_proc = None

                            max_memory_mb = 0.0
                            cpu_percentages = []
                            
                            # 모니터링 루프
                            dot_timer = 0
                            while process.poll() is None:
                                if ps_proc:
                                    try:
                                        mem_info = ps_proc.memory_info()
                                        rss_mb = mem_info.rss / (1024 * 1024)
                                        if rss_mb > max_memory_mb:
                                            max_memory_mb = rss_mb
                                        
                                        cpu_percentages.append(ps_proc.cpu_percent(interval=None))
                                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                                        break
                                
                                time.sleep(0.1)
                                
                                # 사용자에게 살아있음을 알리기 위해 1초마다 점(.) 출력
                                dot_timer += 1
                                if dot_timer % 10 == 0:
                                    print(".", end="", flush=True)

                            end_time = time.perf_counter()
                            net_io_end = psutil.net_io_counters()
                            
                            # 파일 포인터를 처음으로 돌려서 내용 읽기
                            temp_stdout.seek(0)
                            temp_stderr.seek(0)
                            stdout_data = temp_stdout.read()
                            stderr_data = temp_stderr.read()

                        # --- 데이터 처리 ---
                        elapsed_time = end_time - start_time
                        avg_cpu = sum(cpu_percentages) / len(cpu_percentages) if cpu_percentages else 0.0
                        
                        net_sent = net_io_end.bytes_sent - net_io_start.bytes_sent
                        net_recv = net_io_end.bytes_recv - net_io_start.bytes_recv
                        
                        total_files_scanned += 1

                        files_handle["time"].write(f"[{yaml_file.name}]: {elapsed_time:.4f} sec\n")
                        files_handle["cpu"].write(f"[{yaml_file.name}]: {avg_cpu:.2f} %\n")
                        files_handle["memory"].write(f"[{yaml_file.name}]: {max_memory_mb:.2f} MB\n")
                        files_handle["network"].write(f"[{yaml_file.name}]: Sent={net_sent} / Recv={net_recv} (Bytes)\n")

                        print(f" Done! ({elapsed_time:.2f}s)")

                        # Kubescape는 UTF-8 출력을 주로 하므로 디코딩 시도
                        # 윈도우 한글 깨짐 방지를 위해 cp949와 utf-8을 순차적으로 시도하거나 errors='ignore' 유지
                        stdout_str = stdout_data.decode('utf-8', errors='ignore')
                        stderr_str = stderr_data.decode('utf-8', errors='ignore')

                        results_file.write("\n" + "=" * 60 + "\n")
                        results_file.write(f"Results for: {yaml_file.name}\n")
                        results_file.write("=" * 60 + "\n")
                        results_file.write(stdout_str)
                        if stderr_str:
                            results_file.write("\n--- [STDERR] ---\n")
                            results_file.write(stderr_str)

                    except Exception as e:
                        print(f"\n🚨 [Error] {yaml_file.name} 처리 중 오류: {e}")
                        for f in files_handle.values():
                            f.write(f"ERROR scanning {yaml_file.name}: {e}\n")

        for f in files_handle.values():
            f.close()

        print("\n" + "=" * 60)
        print(f"🎉 모든 스캔 완료. 로그는 '{LOG_DIR.resolve()}' 폴더에 저장되었습니다.")
        print(f"총 {total_files_scanned}개 파일 분석됨.")

    except Exception as e:
        print(f"🚨 [Critical Error] 프로그램 실행 중 오류 발생: {e}")

if __name__ == "__main__":
    run_scans_and_monitor()