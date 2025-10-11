# parsers/enisa_parser_dynamic_v4.py
import fitz  # PyMuPDF
import re
import os
from typing import List, Dict

# -----------------------------------------------------
# 🧹 텍스트 정제 함수
# -----------------------------------------------------
def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"([a-zA-Z])-\n([a-zA-Z])", r"\1\2", text)
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        if re.search(r"TECHNICAL IMPLEMENTATION GUIDANCE|June \d{4}, version \d\.\d", line, re.IGNORECASE) or \
           re.match(r"^\s*enisa\s*$", line, re.IGNORECASE) or \
           re.match(r"^\s*\d+\s*$", line):
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)
    text = re.sub(r"\s*\(\d+\)", "", text)
    text = re.sub(r"Source: \S+", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\b(GUIDANCE|EXAMPLES OF EVIDENCE|TIPS)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*[•\u2022\u25e6o-]\s*", "- ", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(\n\s*){2,}", "\n", text)
    return text.strip()

# -----------------------------------------------------
# 🎯 특정 구간 추출 (GUIDANCE, EVIDENCE, TIPS)
# -----------------------------------------------------
def _extract_specific_block(text: str, start_keyword: str, end_keywords: List[str]) -> str:
    end_pattern = "|".join(f"\\b{re.escape(k)}\\b" for k in end_keywords)
    pattern = rf"(?is)\b{re.escape(start_keyword)}\b([\s\S]*?)(?=(?:{end_pattern})|$)"
    match = re.search(pattern, text)
    return _clean_text(match.group(1)) if match else ""

# -----------------------------------------------------
# 📄 메인 파서 함수
# -----------------------------------------------------
def parse(pdf_path: str) -> List[Dict]:
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"[ERROR] PDF 파일을 열 수 없습니다: {e}")
        return []

    source_filename = os.path.basename(pdf_path)

    # --- 목차(TOC) 탐색 ---
    toc_start_page = -1
    intro_page = -1

    for i, page in enumerate(doc):
        text = page.get_text("text")
        if toc_start_page == -1 and "TABLE OF CONTENTS" in text:
            toc_start_page = i
        if toc_start_page != -1 and re.search(r"^\s*INTRODUCTION\s*$", text, re.MULTILINE):
            if "TABLE OF CONTENTS" not in text:
                intro_page = i
                break

    toc_text = ""
    if toc_start_page != -1:
        toc_end_page = intro_page if intro_page != -1 else len(doc)
        toc_text = "".join([doc[i].get_text("text") for i in range(toc_start_page, toc_end_page)])
    else:
        toc_text = "".join([page.get_text("text") for page in doc])

    # -----------------------------------------------------
    # 📘 챕터 / 섹션 추출
    # -----------------------------------------------------
    chapter_map = {}
    sections_map = {}

    pattern_chapter = re.compile(r"(?m)^\s*(\d{1,3})\.\s*(.+)")
    pattern_section = re.compile(r"(?m)^\s*(\d+\.\d+)\s*(.+)")

    for line in toc_text.split("\n"):
        line = line.strip()
        if not line:
            continue

        chap_match = pattern_chapter.match(line)
        if chap_match:
            chap_id, chap_title = chap_match.groups()
            if "INTRODUCTION" not in chap_title:
                chapter_map[chap_id] = chap_title.strip()

        sec_match = pattern_section.match(line)
        if sec_match:
            sec_id, sec_title = sec_match.groups()
            sections_map[sec_id] = sec_title.strip()

    # -----------------------------------------------------
    # 🧩 본문 파싱
    # -----------------------------------------------------
    full_text = "".join([page.get_text("text") for page in doc])
    doc.close()

    split_pattern = r"(?m)(^\d{1,3}\.\d{1,2}\.\d{1,2}\.)"
    blocks = re.split(split_pattern, full_text)

    structured_data = []
    for i in range(1, len(blocks), 2):
        req_id_with_dot = blocks[i]
        req_id = req_id_with_dot.rstrip(".")
        block_content = blocks[i + 1]

        try:
            chapter_num = req_id.split(".")[0]
            chapter_title = chapter_map.get(chapter_num, "N/A")
        except (ValueError, IndexError):
            chapter_title = "N/A"

        section_id = ".".join(req_id.split(".")[:2])
        section_title = sections_map.get(section_id, "N/A")

        req_text_part = re.split(r"\bGUIDANCE\b", block_content, maxsplit=1, flags=re.IGNORECASE)[0]
        requirement_text = _clean_text(req_text_part)
        guidance_text = _extract_specific_block(block_content, "GUIDANCE", ["EXAMPLES OF EVIDENCE", "TIPS"])
        evidence_text = _extract_specific_block(block_content, "EXAMPLES OF EVIDENCE", ["TIPS", "GUIDANCE"])
        tips_text = _extract_specific_block(block_content, "TIPS", ["GUIDANCE", "EXAMPLES OF EVIDENCE"])

        structured_data.append({
            "id": req_id,
            "chapter_title": chapter_title,
            "section_id": section_id,
            "section_title": section_title,
            "requirement_text": requirement_text,
            "guidance": guidance_text,
            "evidence": evidence_text,
            "tips": tips_text,
            "source": source_filename
        })

    return structured_data

# -----------------------------------------------------
# 🧪 실행 테스트
# -----------------------------------------------------
if __name__ == "__main__":
    pdf_path = r"source_documents\ENISA_Technical_implementation_guidance_on_cybersecurity_risk_management_measures_version_1.0.pdf"

    if os.path.exists(pdf_path):
        out = parse(pdf_path)
        print(f"\n🔍 총 추출 항목: {len(out)}개")

        if out:
            print("\n---추출 결과 샘플---")
            samples = [item for item in out if item['id'] in ['1.1.1', '3.2.1', '5.1.1', '10.1.1']]
            for item in samples:
                print(f"  - ID: {item['id']} | Chapter: '{item['chapter_title']}' | Section: '{item['section_title']}'")

            import json
            with open("structured_enisa_dynamic_v4.json", "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            print("\n✅ 완료 → structured_enisa_dynamic_v4.json 생성됨")
    else:
        print(f"[ERROR] PDF 파일을 찾을 수 없습니다: {pdf_path}")
