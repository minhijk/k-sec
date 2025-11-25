import subprocess
import os
from pathlib import Path
import sys
import time
import psutil
import tempfile
import shutil

# --- 설정 (WSL/Linux 환경) ---

KUBELINTER_EXE_PATH = "kube-linter"

TARGET_DIRECTORIES = [Path("vulnerable"), Path("secure")]
LOG_DIR = Path("kubelinter")

BENCH_LOGS = {
    "time": LOG_DIR / "kubelinter_benchmark_time.log",
    "cpu": LOG_DIR / "kubelinter_benchmark_cpu.log",
    "memory": LOG_DIR / "kubelinter_benchmark_memory.log",
    "network": LOG_DIR / "kubelinter_benchmark_network.log"
}

RESULTS_SUFFIX = "_kubelinter_results.log"

# --- --- ---

def run_scans_and_monitor():
    print("KubeLinter 성능 분석(CPU Average Only)을 시작합니다...")
    
    # 실행 파일 위치 확인
    resolved_path = shutil.which(KUBELINTER_EXE_PATH)
    
    if resolved_path:
        print(f" Executable Found: {resolved_path}")
    else:
        print(f"🚨 [FATAL] '{KUBELINTER_EXE_PATH}' 명령어를 찾을 수 없습니다.")
        sys.exit(1)
    
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        print(f"📂 Logs Directory: {LOG_DIR.resolve()}")
    except Exception as e:
        print(f"🚨 [Fatal] 로그 폴더 생성 실패: {e}")
        sys.exit(1)

    # 시스템 논리 코어 개수 (CPU 사용량 정규화용)
    logical_core_count = psutil.cpu_count(logical=True)
        
    print("-" * 60)

    try:
        files_handle = {}
        for key, filepath in BENCH_LOGS.items():
            f = open(filepath, 'w', encoding='utf-8')
            f.write(f"--- KubeLinter Benchmark: {key.upper()} ---\n")
            files_handle[key] = f

        total_files_scanned = 0
        
        for dir_path in TARGET_DIRECTORIES:
            abs_dir_path = dir_path.resolve()
            results_log_path = LOG_DIR / f"{dir_path.name}{RESULTS_SUFFIX}"
            print(f"\nProcessing Directory: {abs_dir_path}")
            
            for f in files_handle.values():
                f.write(f"\n--- Directory: {dir_path.name} ---\n")

            if not dir_path.is_dir():
                print(f"🚨 [Error] 디렉터리 없음: {abs_dir_path}")
                continue

            yaml_files = sorted(dir_path.glob("case-*.yaml"))
            if not yaml_files:
                print(f"🚨 [Warning] '{abs_dir_path}'에 case-*.yaml 파일이 없습니다.")
                continue

            with open(results_log_path, 'w', encoding='utf-8') as results_file:
                results_file.write(f"--- KubeLinter Scan Results for: {dir_path.name} ---\n")

                for yaml_file in yaml_files:
                    command = [resolved_path, "lint", str(yaml_file)]
                    
                    print(f"  > Scanning {yaml_file.name} ", end="", flush=True)

                    try:
                        start_time = time.perf_counter()
                        net_io_start = psutil.net_io_counters()
                        
                        with tempfile.TemporaryFile() as temp_stdout, tempfile.TemporaryFile() as temp_stderr:
                            
                            process = subprocess.Popen(
                                command,
                                stdout=temp_stdout,
                                stderr=temp_stderr
                            )

                            try:
                                ps_proc = psutil.Process(process.pid)
                                ps_proc.cpu_percent(interval=None) # 초기화
                            except psutil.NoSuchProcess:
                                ps_proc = None

                            max_memory_mb = 0.0
                            cpu_percentages = []
                            
                            dot_timer = 0
                            
                            while process.poll() is None:
                                if ps_proc:
                                    try:
                                        with ps_proc.oneshot():
                                            mem_info = ps_proc.memory_info()
                                            rss_mb = mem_info.rss / (1024 * 1024)
                                            if rss_mb > max_memory_mb:
                                                max_memory_mb = rss_mb
                                            
                                            raw_cpu = ps_proc.cpu_percent(interval=None)
                                            
                                            # 코어 수로 정규화 (0~100% 범위)
                                            normalized_cpu = raw_cpu / logical_core_count
                                            
                                            if normalized_cpu > 100.0:
                                                normalized_cpu = 100.0
                                            
                                            cpu_percentages.append(normalized_cpu)

                                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                                        break
                                
                                # 짧은 주기 유지 (정확도 위해)
                                time.sleep(0.01)
                                
                                dot_timer += 1
                                if dot_timer % 100 == 0:
                                    print(".", end="", flush=True)

                            end_time = time.perf_counter()
                            net_io_end = psutil.net_io_counters()
                            
                            temp_stdout.seek(0)
                            temp_stderr.seek(0)
                            stdout_data = temp_stdout.read()
                            stderr_data = temp_stderr.read()

                        # --- 데이터 처리 ---
                        elapsed_time = end_time - start_time
                        
                        if cpu_percentages:
                            avg_cpu = sum(cpu_percentages) / len(cpu_percentages)
                        else:
                            avg_cpu = 0.0
                        
                        net_sent = net_io_end.bytes_sent - net_io_start.bytes_sent
                        net_recv = net_io_end.bytes_recv - net_io_start.bytes_recv
                        
                        total_files_scanned += 1

                        # [수정됨] Kubescape 스타일 출력 포맷 (평균만 출력)
                        files_handle["time"].write(f"[{yaml_file.name}]: {elapsed_time:.4f} sec\n")
                        files_handle["cpu"].write(f"[{yaml_file.name}]: {avg_cpu:.2f} %\n")
                        files_handle["memory"].write(f"[{yaml_file.name}]: {max_memory_mb:.2f} MB\n")
                        files_handle["network"].write(f"[{yaml_file.name}]: Sent={net_sent} / Recv={net_recv} (Bytes)\n")

                        print(f" Done! ({elapsed_time:.4f}s)")

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