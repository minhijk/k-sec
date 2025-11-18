import tempfile
import os
import difflib
import re
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import PreservedScalarString
from langsmith import traceable

# --- 1. apply_diff (수정 없음) ---
def apply_diff(original_text: str, diff_text: str) -> str:
    """
    LLM이 생성한 unified diff 포맷을 실제 YAML에 적용.
    적용 실패 시 원본을 그대로 반환.
    """
    try:
        diff_lines = diff_text.splitlines(keepends=True)
        patched_text = []
        for line in diff_lines:
            if line.startswith('+') and not line.startswith('+++'):
                patched_text.append(line[1:])
            elif line.startswith('-') or line.startswith('---') or line.startswith('+++'):
                continue
            else:
                patched_text.append(line)
        return ''.join(patched_text)
    except Exception as e:
        print(f"[DiffHandler] ❌ Diff 적용 실패: {e}")
        return original_text

# --- 2. save_temp_patch (수정 없음) ---
def save_temp_patch(diff_text: str) -> str:
    """Diff 텍스트를 임시 파일로 저장하고 경로 반환"""
    tmp_path = os.path.join(tempfile.gettempdir(), "ksec_diff.patch")
    with open(tmp_path, "w", encoding="utf-8") as f: # utf-8 적용됨
        f.write(diff_text)
    print(f"[DiffHandler] 💾 Patch 저장 완료: {tmp_path}")
    return tmp_path

# --- 3. save_temp_yaml (수정 없음) ---
def save_temp_yaml(content: str, suffix: str = "_patched") -> str:
    """임시 YAML 파일로 저장 (비교용)"""
    tmp_path = os.path.join(tempfile.gettempdir(), f"ksec_yaml{suffix}.yaml")
    with open(tmp_path, "w", encoding="utf-8") as f: # utf-8 적용됨
        f.write(content)
    print(f"[DiffHandler] 🧾 YAML 저장 완료: {tmp_path}")
    return tmp_path


# --- 4. parse_line_suggestions (누락되었던 함수) ---
@traceable
def parse_line_suggestions(llm_output: str) -> list[dict]:
    """
    LLM이 생성한 'YAML 경로' 기반 수정 제안을 파싱합니다.
    """
    suggestions = []
    
    try:
        content_match = re.search(r"\[수정 제안 목록 시작\](.*?)\[수정 제안 목록 끝\]", llm_output, re.DOTALL)
        if not content_match:
            print("[PARSE_WARN] '수정 제안 목록' 태그를 찾을 수 없습니다.")
            return []
        content = content_match.group(1).strip()
    except Exception as e:
        print(f"[PARSE_ERROR] 목록 추출 실패: {e}")
        return []

    suggestion_blocks = re.split(r"\n*\s*\(\d+\)\s*\n", content)

    type_pattern = re.compile(r"\[유형\]:\s*(.*)")
    path_pattern = re.compile(r"\[YAML 경로\]:\s*(.*)")
    original_val_pattern = re.compile(r"\[원본 값\]:\s*(.*)")
    proposal_pattern = re.compile(r"\[수정 제안\]:\s*([\s\S]*)\[사유\]")
    reason_pattern = re.compile(r"(?s)\[사유\]:\s*(.*)\Z")

    for i, block in enumerate(suggestion_blocks):
        if not block.strip():
            continue
            
        try:
            type_match = type_pattern.search(block)
            path_match = path_pattern.search(block)
            val_match = original_val_pattern.search(block)
            
            proposal_raw = ""
            reason_raw = ""

            reason_match = reason_pattern.search(block)
            if reason_match:
                reason_raw = reason_match.group(1).strip()
                proposal_match = proposal_pattern.search(block)
                if proposal_match:
                    proposal_raw = proposal_match.group(1).strip()
            else:
                proposal_match = re.search(r"\[수정 제안\]:\s*(.*)", block)
                if proposal_match:
                    proposal_raw = proposal_match.group(1).strip()

            
            suggestion_item = {
                "id": f"suggestion_{i}",
                "type": (type_match.group(1).strip() if type_match else "추가"),
                "path": (path_match.group(1).strip() if path_match else ""),
                "original_value": (val_match.group(1).strip() if val_match else ""),
                "proposed_value": proposal_raw,
                "reason": (reason_raw if reason_raw else "N/A"),
                "selected": True
            }

            if suggestion_item["path"] and (suggestion_item["proposed_value"] or suggestion_item["type"] == "삭제"):
                 suggestions.append(suggestion_item)
            
        except Exception as e:
            print(f"[PARSE_ERROR] 블록 파싱 실패 (ID: {i}): {e}\nBlock: {block[:50]}...")
            continue
            
    print(f"[PARSE_SUCCESS] {len(suggestions)}개의 'YAML 경로' 기반 제안을 파싱했습니다.")
    return suggestions


# --- 5. apply_selected_suggestions (모든 버그 수정된 버전) ---
@traceable
def apply_selected_suggestions(original_yaml: str, selected_suggestions: list[dict]) -> str:
    """ 
    선택된 'YAML 경로' 기반 제안을 ruamel.yaml을 사용해 적용합니다.
    [결정판: 다중문서(---), Round-Trip, 타입 변환, 인코딩(utf-8) 모두 적용]
    """
    yaml = YAML()
    yaml.typ = 'rt' # Round-Trip 모드 (스타일 보존)
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    
    docs = []
    try:
        # 다중 문서(---) 처리를 위해 load_all 사용
        docs = list(yaml.load_all(original_yaml))
        if not docs:
            raise Exception("YAML 문서가 비어있습니다.")
    except Exception as e:
        print(f"[ApplyPatch-ERROR] 원본 YAML 로드 실패: {e}")
        return original_yaml

    # --- 헬퍼 함수 _set_value_by_path (견고한 버전) ---
    def _set_value_by_path(data_obj, path_str: str, sug_type: str, new_value_str: str):
        keys = path_str.split('.')
        current_level = data_obj

        for i, key in enumerate(keys):
            is_last_key = (i == len(keys) - 1)
            
            if isinstance(current_level, dict):
                # 딕셔너리 탐색
                if key not in current_level:
                    if not is_last_key:
                        print(f"[ApplyPatch-WARN] 경로 '{path_str}'의 키 '{key}'가 존재하지 않아 건너뜁니다.")
                        return
                    # (마지막 키이고 '추가'인 경우는 아래에서 처리됨)

                if is_last_key:
                    # 마지막 키 도달 (값 처리)
                    new_value_as_yaml_obj = None
                    if '\n' in new_value_str:
                        new_value_as_yaml_obj = PreservedScalarString(new_value_str)
                    else:
                        try:
                            new_value_as_yaml_obj = yaml.load(new_value_str)
                        except Exception:
                            new_value_as_yaml_obj = new_value_str

                    if sug_type == "수정":
                        current_level[key] = new_value_as_yaml_obj
                        print(f"[ApplyPatch] MODIFIED path '{path_str}'")
                    elif sug_type == "추가":
                        new_data = new_value_as_yaml_obj
                        if isinstance(new_data, dict) and isinstance(current_level, dict):
                            current_level.update(new_data)
                        else:
                            current_level[key] = new_data
                        print(f"[ApplyPatch] ADDED to path '{path_str}'")
                    elif sug_type == "삭제":
                        if key in current_level:
                            del current_level[key]
                            print(f"[ApplyPatch] DELETED path '{path_str}'")
                    return
                else:
                    current_level = current_level[key]

            elif isinstance(current_level, list):
                # 리스트 탐색
                if key.isdigit():
                    idx = int(key)
                    if idx >= len(current_level):
                        print(f"[ApplyPatch-WARN] 경로 '{path_str}'의 인덱스 {idx}가 범위를 벗어남, 건너뜁니다.")
                        return
                    
                    if is_last_key:
                        # 리스트의 마지막 항목 (값 처리)
                        new_value_as_yaml_obj = None
                        if '\n' in new_value_str:
                            new_value_as_yaml_obj = PreservedScalarString(new_value_str)
                        else:
                            try:
                                new_value_as_yaml_obj = yaml.load(new_value_str)
                            except Exception:
                                new_value_as_yaml_obj = new_value_str
                        
                        if sug_type == "수정":
                            current_level[idx] = new_value_as_yaml_obj
                            print(f"[ApplyPatch] MODIFIED list item at '{path_str}'")
                        elif sug_type == "삭제":
                            del current_level[idx]
                            print(f"[ApplyPatch] DELETED list item at '{path_str}'")
                        return
                    else:
                        current_level = current_level[idx]
                else:
                    print(f"[ApplyPatch-WARN] 경로 '{path_str}' 탐색 중 리스트에서 비숫자 키 '{key}'를 만나 실패, 건너뜁니다.")
                    return
            else:
                print(f"[ApplyPatch-WARN] 경로 '{path_str}' 탐색 중 예상치 못한 타입 {type(current_level)} 만나 실패, 건너뜁니다.")
                return
    # --- 헬퍼 함수 끝 ---

    print(f"[ApplyPatch] {len(selected_suggestions)}개의 '경로 기반' 제안 적용 시작...")

    for sug in selected_suggestions:
        sug_type = sug.get("type")
        path = sug.get("path")
        value = sug.get("proposed_value")
        
        try:
            # 첫 번째 문서(docs[0])에만 패치 적용
            if docs and isinstance(docs[0], (dict, list)):
                 _set_value_by_path(docs[0], path, sug_type, value)
            else:
                 print(f"[ApplyPatch-WARN] 패치할 유효한 문서(docs[0])를 찾지 못했습니다.")
        except Exception as e:
            print(f"[ApplyPatch-ERROR] 경로 '{path}' 적용 중 오류 발생: {e}")
            continue
            
    try:
        # [핵심 수정] 임시 파일 저장 시 encoding='utf-8' 명시
        with tempfile.NamedTemporaryFile(delete=False, mode='w', encoding='utf-8') as f:
            yaml.dump_all(docs, f) # 다중 문서 덤프
            temp_path = f.name
        
        # [핵심 수정] 임시 파일 읽을 시 encoding='utf-8' 명시
        with open(temp_path, 'r', encoding='utf-8') as f:
            final_yaml_str = f.read()
        
        os.remove(temp_path)
        return final_yaml_str
        
    except Exception as e:
        # 이 부분에서 'cp949' 에러가 발생했던 것임
        print(f"[ApplyPatch-ERROR] 최종 YAML 덤프 실패: {e}")
        return original_yaml