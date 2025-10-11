import json
import re

def _clean_text(text: str) -> str:
    """텍스트 정제: 불필요한 문구, 페이지 번호, 공백 제거"""
    if not text:
        return ""
    text = re.sub(r"(?i)TECHNICAL IMPLEMENTATION GUIDANCE", "", text)
    text = re.sub(r"(?i)ENISA|June\s+\d{4}|version\s*\d+\.\d+", "", text)
    text = re.sub(r"Page\s*\d+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def get_cis_categories(cis_id: str):
    """CIS ID에 따라 category_l1, category_l2 자동 매핑"""
    mappings = {
        "1": ("Control Plane Components", "API Server Configuration"),
        "2": ("Control Plane Components", "Scheduler / Controller Manager"),
        "3": ("Control Plane Components", "etcd Configuration"),
        "4": ("Worker Node Security", "Kubelet Configuration"),
        "5": ("Pod Security Policies", "Service Account Management"),
        "6": ("Network Policies", "CNI Plugin & Networking"),
        "7": ("Logging and Auditing", "Audit & Log Configuration"),
        "8": ("Configuration Files", "File Ownership & Permissions"),
        "9": ("RBAC and Authentication", "Access Control Enforcement"),
        "10": ("Pod Security Admission", "Policy Configuration")
    }
    prefix = cis_id.split('.')[0]
    return mappings.get(prefix, ("CIS Benchmark Recommendations", ""))

def normalize_cis(item):
    """CIS 데이터를 NIST 포맷으로 변환 + 카테고리 보강"""
    cat1, cat2 = get_cis_categories(item.get("id", ""))
    details = {
        "rationale": item.get("rationale", ""),
        "impact": item.get("impact", ""),
        "audit": item.get("audit", ""),
        "default_value": item.get("default_value", ""),
        "references": item.get("references", ""),
        "cis_controls": item.get("cis_controls", "")
    }
    return {
        "id": f"CIS-{item.get('id', '')}",
        "source": item.get("source", "cis_benchmark.pdf"),
        "category_l1": cat1,
        "category_l2": cat2,
        "title": item.get("title", ""),
        "content_description": _clean_text(item.get("description", "")),
        "content_remediation": _clean_text(item.get("remediation", "")),
        "details": details
    }

def normalize_enisa(item):
    """ENISA 데이터를 NIST 포맷에 맞게 변환 + 텍스트 정제 강화"""
    details = {
        "evidence": _clean_text(item.get("evidence", "")),
        "tips": _clean_text(item.get("tips", ""))
    }
    return {
        "id": f"ENISA-{item.get('id', '')}",
        "source": item.get("source", "enisa_tig.pdf"),
        "category_l1": _clean_text(item.get("chapter_title", "ENISA Guidance")),
        "category_l2": _clean_text(item.get("section_title", "")),
        "title": _clean_text(item.get("section_title", "")),
        "content_description": _clean_text(item.get("requirement_text", "")),
        "content_remediation": _clean_text(" ".join(filter(None, [item.get("guidance", ""), item.get("tips", "")]))),
        "details": details
    }

def normalize_nist(item):
    """NIST는 이미 통일된 구조이므로 그대로 반환"""
    return item

def unify_json(nist_path, cis_path, enisa_path, output_path):
    def load_json(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    nist_data = load_json(nist_path)
    cis_data = load_json(cis_path)
    enisa_data = load_json(enisa_path)

    unified = []
    unified.extend([normalize_nist(i) for i in nist_data])
    unified.extend([normalize_cis(i) for i in cis_data])
    unified.extend([normalize_enisa(i) for i in enisa_data])

    print(f"✅ 통합 완료: NIST={len(nist_data)}, CIS={len(cis_data)}, ENISA={len(enisa_data)} → 총 {len(unified)} 항목")

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(unified, f, ensure_ascii=False, indent=2)

    print(f"📄 결과 저장됨: {output_path}")

if __name__ == "__main__":
    # 백슬래시(\)를 슬래시(/)로 변경
    unify_json(
        nist_path="parser/parsers_output/structured_nist.json",
        cis_path="parser/parsers_output/structured_cis.json",
        enisa_path="parser/parsers_output/structured_enisa.json",
        output_path="structured_all.json"
    )