# ============================================================
# NIST SP 800-190 Parser — 최종 완성 버전 (v9)
# ------------------------------------------------------------
# 주요 개선:
#   - meta 제거, 단일 리스트 출력
#   - Section 5(Scenarios) 자동 포함
#   - 본문 페이지 및 잘린 항목(3.3.3, 3.4.2 등) 완전 복구
# ============================================================

import fitz  # PyMuPDF
import re
import os
import json
from datetime import datetime
from typing import List, Dict, Tuple

# ---------------------------
# 텍스트 정제 함수
# ---------------------------
def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"NIST SP 800-190|APPLICATION CONTAINER SECURITY GUIDE", "", text, flags=re.IGNORECASE)
    text = re.sub(r"This publication is available[^\n]+", "", text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text.replace('\n', ' '))
    return text.strip()

# ---------------------------
# Section 3 & 4 Parser
# ---------------------------
def parse_sections_3_and_4(doc: fitz.Document) -> Tuple[Dict, Dict]:
    print("[INFO] Section 3 (Risks) & 4 (Countermeasures) 파싱 시작...")
    all_items = {}
    current_id, current_title, current_content = None, "", []

    # ID 패턴 개선 (3.3.3 등 완전 추출)
    item_pattern = re.compile(r"^\s*([34]\.\d+\.\d+)\s+([A-Za-z].*)$")

    # 본문 페이지 (약 12~39쪽)
    for page_num in range(12, 39):
        page = doc.load_page(page_num)
        lines = page.get_text("text").split('\n')

        for line in lines:
            if re.match(r"^\s*(\d+|[ivx]+)\s*$", line.strip().lower()):
                continue

            match = item_pattern.match(line)
            if match:
                if current_id:
                    all_items[current_id] = {
                        "title": current_title,
                        "content": " ".join(current_content)
                    }
                current_id = match.group(1)
                current_title = match.group(2).strip()
                current_content = []
            elif current_id:
                # 줄이 소문자로 시작하면 앞 문장에 이어붙임 (페이지 잘림 보정)
                if current_content and re.match(r"^[a-z]", line.strip()):
                    current_content[-1] += " " + line.strip()
                else:
                    current_content.append(line.strip())

    if current_id:
        all_items[current_id] = {"title": current_title, "content": " ".join(current_content)}

    risks = {k: v for k, v in all_items.items() if k.startswith('3.')}
    counters = {k: v for k, v in all_items.items() if k.startswith('4.')}
    print(f"[INFO] Section 3: {len(risks)}개, Section 4: {len(counters)}개 추출 완료.")
    return risks, counters

# ---------------------------
# Section 5 Parser
# ---------------------------
def parse_section_5(doc: fitz.Document) -> List[Dict]:
    print("[INFO] Section 5 (Scenarios) 파싱 시작...")
    scenarios = []
    full_text_s5 = ""
    for page_num in range(39, 43):  # Section 5
        full_text_s5 += doc.load_page(page_num).get_text("text")

    item_pattern = re.compile(r"^\s*(5\.\d)\s+(.*)", re.MULTILINE)
    matches = list(item_pattern.finditer(full_text_s5))

    for i, match in enumerate(matches):
        sid = match.group(1)
        title = match.group(2).strip()
        start_pos = match.end()
        end_pos = matches[i+1].start() if i + 1 < len(matches) else len(full_text_s5)
        content = full_text_s5[start_pos:end_pos].strip()

        # 완화 조치 구분
        split_match = re.search(r"(Relevant mitigations.*?:)", content, re.IGNORECASE)
        if split_match:
            split_point = split_match.start()
            desc = content[:split_point]
            rem = content[split_point:]
        else:
            desc, rem = content, ""

        scenarios.append({
            "id": f"NIST-{sid}",
            "source": "NIST.SP.800-190.pdf",
            "category_l1": "Container Threat Scenarios",
            "category_l2": clean_text(title),
            "title": clean_text(title),
            "content_description": clean_text(desc),
            "content_remediation": clean_text(rem),
            "details": {}
        })
    print(f"[INFO] Section 5: {len(scenarios)}개 항목 추출 완료.")
    return scenarios

# ---------------------------
# 통합 Parser
# ---------------------------
def parse(pdf_path: str) -> List[Dict]:
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"[ERROR] PDF 열기 실패: {e}")
        return []

    risks, counters = parse_sections_3_and_4(doc)
    scenarios = parse_section_5(doc)

    structured_data = []
    category_map_l2 = {
        '1': 'Image Risks', '2': 'Registry Risks', '3': 'Orchestrator Risks',
        '4': 'Container Risks', '5': 'Host OS Risks'
    }

    print("[INFO] Risk와 Countermeasure 병합 중...")
    for rid, rinfo in risks.items():
        cm_id = '4' + rid[1:]
        cm_info = counters.get(cm_id)
        sec_num = rid.split('.')[1]

        structured_data.append({
            "id": f"NIST-{rid}",
            "source": os.path.basename(pdf_path),
            "category_l1": "Major Risks and Countermeasures",
            "category_l2": category_map_l2.get(sec_num, "Unknown"),
            "title": clean_text(rinfo["title"]),
            "content_description": clean_text(rinfo["content"]),
            "content_remediation": clean_text(cm_info["content"]) if cm_info else "",
            "details": {}
        })

    # Section 5 추가
    structured_data.extend(scenarios)
    structured_data.sort(key=lambda x: [float(p) if p.replace('.', '', 1).isdigit() else p for p in x['id'].replace('NIST-', '').split('.')])

    print(f"\n✅ [완료] 총 {len(structured_data)}개 항목 추출 (Section 5 포함)")
    return structured_data

# ---------------------------
# 실행 (PDF → JSON)
# ---------------------------
if __name__ == "__main__":
    pdf_path = "source_documents/NIST.SP.800-190.pdf"
    output_dir = "parsers_output"
    output_filename = "structured_nist.json"

    if os.path.exists(pdf_path):
        os.makedirs(output_dir, exist_ok=True)
        data = parse(pdf_path)
        if data:
            output_path = os.path.join(output_dir, output_filename)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"✅ JSON 결과 저장 완료 → {output_path}")
    else:
        print(f"[ERROR] PDF 파일을 찾을 수 없습니다: {pdf_path}")
