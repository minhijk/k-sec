import fitz
import os

# CTR 문서의 실제 목차를 리스트로 정의 (파싱의 기준점)
CTR_SECTIONS = [
    "Kubernetes Pod Security",
    "Network Separation and Hardening",
    "Authentication and Authorization",
    "Log Auditing and Monitoring",
    "Application Security Practices"
]
STOP_WORD = "Appendix A"

def parse(pdf_path: str) -> list[dict]:
    """
    CTR (Kubernetes Hardening Guide) PDF의 실제 목차 구조를 동적으로 파악하여 파싱합니다.
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Error opening PDF: {e}")
        return []

    source_filename = os.path.basename(pdf_path)
    structured_data = []
    
    current_title = None
    current_content = ""
    stop_parsing = False
    
    for page in doc:
        if stop_parsing: break
        lines = page.get_text("text").split('\n')
        for line in lines:
            stripped_line = line.strip()
            
            if stripped_line == STOP_WORD:
                stop_parsing = True
                break
            
            is_section_title = False
            for title in CTR_SECTIONS:
                if stripped_line == title:
                    if current_title:
                        structured_data.append({
                            "section_title": current_title,
                            "content": current_content.strip(),
                        })
                    current_title = title
                    current_content = ""
                    is_section_title = True
                    break
            
            if current_title and not is_section_title:
                current_content += line + '\n'

    if current_title and current_content.strip():
        structured_data.append({
            "section_title": current_title,
            "content": current_content.strip()
        })
    
    # 문서 고유의 구조를 반영한 최종 JSON 생성
    final_data = []
    for item in structured_data:
        final_data.append({
            "id": item["section_title"].lower().replace(" ", "-"),
            "title": item["section_title"],
            "content": item["content"],
            "source": source_filename
        })
        
    return final_data