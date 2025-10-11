# main_ingest.py (파싱 + 통합 버전)

import json
import os
from typing import Dict, Any, List

# --- 1. 모듈 임포트 ---
# 각 문서 파서와 최종 통합 함수를 임포트합니다.
from parsers import cis_parser, enisa_parser, nist_parser
from combine_parsers import unify_json

# --- 2. 설정: 처리할 문서와 파서 정의 ---
DOCUMENT_SOURCES = [
    {
        # "parser/" 경로 추가
        "path": "parser/source_documents/CIS_Kubernetes_Benchmark_V1.12_PDF.pdf",
        "parser": cis_parser.parse, 
        "output_file": "structured_cis.json"
    },
    {
        # "parser/" 경로 추가
        "path": "parser/source_documents/ENISA_Technical_implementation_guidance_on_cybersecurity_risk_management_measures_version_1.0.pdf",
        "parser": enisa_parser.parse,
        "output_file": "structured_enisa.json"
    },
    {
        # "parser/" 경로 추가
        "path": "parser/source_documents/NIST.SP.800-190.pdf",
        "parser": nist_parser.parse,
        "output_file": "structured_nist.json"
    }
]


def run_ingestion_pipeline():
    """데이터 파싱부터 최종 통합까지 전체 파이프라인을 실행합니다."""
    # 출력 경로를 "parser/parsers_output"으로 수정
    output_dir = os.path.join("parser", "parsers_output")
    os.makedirs(output_dir, exist_ok=True)
    
    # --- 1단계: 개별 문서 파싱 ---
    print("🚀 1단계: 동적 스키마 파싱을 시작합니다...")
    successful_parses = []
    for source in DOCUMENT_SOURCES:
        file_path = source["path"]
        print(f"\n-> 📄 '{file_path}' 파싱 중...")
        
        if not os.path.exists(file_path):
            print(f"   ❌ 파일 없음: '{file_path}'. 건너뜁니다.")
            continue
        
        data = source["parser"](file_path)
        
        if data:
            output_path = os.path.join(output_dir, source["output_file"])
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            print(f"   ✅ 파싱 성공! {len(data)}개 항목 -> '{output_path}'에 저장 완료")
            successful_parses.append(output_path)
        else:
            print(f"   ❌ 파싱 실패 또는 추출된 데이터가 없습니다.")

    print("\n\n🎉 선택된 문서의 개별 파싱이 완료되었습니다.")
    
    # --- 2단계: 파싱된 JSON 파일 통합 ---
    print("\n🚀 2단계: 파싱된 JSON 파일들을 단일 파일로 통합합니다...")
    
    # unify_json 함수에 필요한 파일 경로들을 정의합니다.
    nist_path = os.path.join(output_dir, "structured_nist.json")
    cis_path = os.path.join(output_dir, "structured_cis.json")
    enisa_path = os.path.join(output_dir, "structured_enisa.json")
    unified_output_path = "structured_all.json"

    # 모든 소스 파일이 존재하는지 확인 후 통합 함수 호출
    required_files = [nist_path, cis_path, enisa_path]
    if all(os.path.exists(p) for p in required_files):
        unify_json(
            nist_path=nist_path,
            cis_path=cis_path,
            enisa_path=enisa_path,
            output_path=unified_output_path
        )
    else:
        print(f"   ❌ 통합 실패: 필요한 JSON 파일 중 일부가 없습니다. 1단계 파싱 결과를 확인해주세요.")
        missing_files = [f for f in required_files if not os.path.exists(f)]
        print(f"   (누락된 파일: {', '.join(missing_files)})")
    
    print("\n\n🎉 모든 문서의 파싱 및 통합이 완료되었습니다.")


if __name__ == "__main__":
    run_ingestion_pipeline()