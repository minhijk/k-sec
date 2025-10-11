import fitz  # PyMuPDF
import re
import os

def parse(pdf_path: str) -> list[dict]:
    """
    사용자가 제공한 원본 코드를 기반으로 CIS Benchmark PDF를 정교하게 파싱합니다.
    URL 처리는 이 함수에서 수행하지 않습니다.
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Error opening or reading PDF file: {e}")
        return []

    source_filename = os.path.basename(pdf_path)
    
    recommendations = []
    current_rec_text = ""
    title_pattern = re.compile(r"^\s*(\d+\.\d+\.\d+)\s+(.*)")

    for page_num in range(14, len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        lines = text.split('\n')

        for line in lines:
            if title_pattern.match(line.strip()):
                if current_rec_text:
                    recommendations.append(current_rec_text)
                current_rec_text = line
            else:
                current_rec_text += "\n" + line
    
    if current_rec_text:
        recommendations.append(current_rec_text)
    
    doc.close()

    structured_data = []
    for rec_text in recommendations:
        rec_text = rec_text.strip()
        
        id_match = re.match(r"(\d+\.\d+\.\d+)", rec_text)
        if not id_match:
            continue
        
        rec_id = id_match.group(1)
        
        if "Profile Applicability:" in rec_text:
            parts = rec_text.split("Profile Applicability:", 1)
            title_text = parts[0]
            body_text = "Profile Applicability:" + parts[1]
        else:
            title_text = rec_text.split('\n')[0]
            body_text = '\n'.join(rec_text.split('\n')[1:])

        cleaned_title = re.sub(r'\s+', ' ', title_text).strip()

        rec_dict = {
            "id": rec_id,
            "title": cleaned_title,
            "description": "", "rationale": "", "impact": "",
            "audit": "", "remediation": "", "default_value": "",
            "references": "", "cis_controls": ""
        }

        keywords = ["Description", "Rationale", "Impact", "Audit", "Remediation", "Default Value", "References", "CIS Controls"]
        
        split_pattern = '|'.join([f'(?={kw}:)' for kw in keywords])
        sections = re.split(split_pattern, body_text)
        
        for section in sections:
            section = section.strip()
            if not section: continue

            for kw in keywords:
                if section.startswith(f"{kw}:"):
                    key = kw.lower().replace(" ", "_")
                    value = section[len(kw)+1:].strip()
                    
                    if key == 'references':
                        lines = value.split('\n')
                        cleaned_lines = [line.strip() for line in lines if line.strip()]
                        rec_dict[key] = '\n'.join(cleaned_lines)
                    else:
                        cleaned_value = re.sub(r'\s+', ' ', value).strip()
                        rec_dict[key] = cleaned_value
                    break
        
        rec_dict["source"] = source_filename
        structured_data.append(rec_dict)

    return structured_data