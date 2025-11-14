# utils/diff_handler.py
import tempfile
import os
import difflib
import re
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import PreservedScalarString

def apply_diff(original_text: str, diff_text: str) -> str:
    """
    LLM이 생성한 unified diff 포맷을 실제 YAML에 적용.
    적용 실패 시 원본을 그대로 반환.
    """
    try:
        # diff 문자열 파싱
        diff_lines = diff_text.splitlines(keepends=True)
        patched_text = []
        # difflib.restore()은 reverse diff 적용용이라 직접 patch 수행
        for line in diff_lines:
            # '+'로 시작하면 추가, '-'로 시작하면 제거
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

def save_temp_patch(diff_text: str) -> str:
    """Diff 텍스트를 임시 파일로 저장하고 경로 반환"""
    tmp_path = os.path.join(tempfile.gettempdir(), "ksec_diff.patch")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(diff_text)
    print(f"[DiffHandler] 💾 Patch 저장 완료: {tmp_path}")
    return tmp_path

def save_temp_yaml(content: str, suffix: str = "_patched") -> str:
    """임시 YAML 파일로 저장 (비교용)"""
    tmp_path = os.path.join(tempfile.gettempdir(), f"ksec_yaml{suffix}.yaml")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[DiffHandler] 🧾 YAML 저장 완료: {tmp_path}")
    return tmp_path



def parse_line_suggestions(llm_output: str) -> list[dict]:
    """
    LLM이 생성한 'YAML 경로' 기반 수정 제안을 파싱합니다.
    (SyntaxError 수정 버전)
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

    # ⭐️ 1. 모든 정규식 패턴 정의
    type_pattern = re.compile(r"\[유형\]:\s*(.*)")
    path_pattern = re.compile(r"\[YAML 경로\]:\s*(.*)")
    original_val_pattern = re.compile(r"\[원본 값\]:\s*(.*)")
    # ⭐️ '사유' 태그가 없어도 제안을 캡처할 수 있도록 수정 (.*?) -> (.*)
    proposal_pattern = re.compile(r"\[수정 제안\]:\s*([\s\S]*)\[사유\]")
    # ⭐️ 사유가 맨 마지막에 오므로, (?s) 플래그로 여러 줄을 포함하고, 문자열 끝(Z)까지 캡처
    reason_pattern = re.compile(r"(?s)\[사유\]:\s*(.*)\Z")

    for i, block in enumerate(suggestion_blocks):
        if not block.strip():
            continue
            
        try:
            # ⭐️ 2. [핵심 수정] 딕셔너리 밖에서 모든 match를 미리 계산합니다.
            type_match = type_pattern.search(block)
            path_match = path_pattern.search(block)
            val_match = original_val_pattern.search(block)
            
            # ⭐️ 제안/사유는 추출 방식이 약간 다름
            proposal_raw = ""
            reason_raw = ""

            # '사유'를 기준으로 '제안'을 먼저 분리
            reason_match = reason_pattern.search(block)
            if reason_match:
                reason_raw = reason_match.group(1).strip()
                # '제안'은 '사유' 태그 전까지의 내용임
                proposal_match = proposal_pattern.search(block)
                if proposal_match:
                    proposal_raw = proposal_match.group(1).strip()
            else:
                # 사유 태그가 없는 경우 (예: (라인 삭제))
                proposal_match = re.search(r"\[수정 제안\]:\s*(.*)", block)
                if proposal_match:
                    proposal_raw = proposal_match.group(1).strip()

            
            # ⭐️ 3. Walrus 연산자(':=') 없이 깔끔하게 딕셔너리 생성
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


def apply_selected_suggestions(original_yaml: str, selected_suggestions: list[dict]) -> str:
    """
    선택된 'YAML 경로' 기반 제안을 ruamel.yaml을 사용해 적용합니다.
    """
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    
    try:
        data = yaml.load(original_yaml)
    except Exception as e:
        print(f"[ApplyPatch-ERROR] 원본 YAML 로드 실패: {e}")
        return original_yaml # 오류 시 원본 반환

    # ⭐️ 1. 경로를 탐색하여 값을 설정/추가/삭제하는 헬퍼 함수
    def _set_value_by_path(data, path_str: str, sug_type: str, new_value_str: str):
        keys = path_str.split('.')
        current_level = data
        
        for i, key in enumerate(keys):
            is_last_key = (i == len(keys) - 1)
            
            # 리스트 인덱스 처리 (예: containers.0)
            if key.isdigit() and isinstance(current_level, list):
                key = int(key)
                if key >= len(current_level):
                    print(f"[ApplyPatch-WARN] 경로 '{path_str}'의 인덱스 {key}가 범위를 벗어남, 건너뜁니다.")
                    return
            # 딕셔너리 키 처리
            elif isinstance(current_level, dict):
                if not is_last_key and key not in current_level:
                    print(f"[ApplyPatch-WARN] 경로 '{path_str}'의 키 {key}가 존재하지 않음, 건너뜁니다.")
                    return
            else:
                print(f"[ApplyPatch-WARN] 경로 '{path_str}' 탐색 중 {type(current_level)} 만나 실패, 건너뜁니다.")
                return

            # 마지막 키(실제 수정 대상)에 도달한 경우
            if is_last_key:
                # ⭐️ 2. 제안 유형(type)별로 작업 분기
                if sug_type == "수정":
                    current_level[key] = new_value_str # ⭐️ 값 수정
                    print(f"[ApplyPatch] MODIFIED path '{path_str}'")
                
                elif sug_type == "추가":
                    # ⭐️ 새 YAML 조각 로드
                    new_data = yaml.load(new_value_str)
                    if isinstance(new_data, dict) and isinstance(current_level, dict):
                        current_level.update(new_data) # ⭐️ 키/값 쌍 추가
                    else:
                         current_level[key] = new_data # ⭐️ (예: metadata.namespace 추가)
                    print(f"[ApplyPatch] ADDED to path '{path_str}'")

                elif sug_type == "삭제":
                    if key in current_level:
                        del current_level[key] # ⭐️ 키 삭제
                        print(f"[ApplyPatch] DELETED path '{path_str}'")
                
                return # 작업 완료
            
            # 다음 레벨로 이동
            current_level = current_level[key]

    print(f"[ApplyPatch] {len(selected_suggestions)}개의 '경로 기반' 제안 적용 시작...")

    # ⭐️ 3. 제안 목록 순회 (역순 정렬 불필요)
    for sug in selected_suggestions:
        sug_type = sug.get("type")
        path = sug.get("path")
        value = sug.get("proposed_value")
        
        # ⭐️ 여러 줄 문자열(예: seccompProfile)을 위한 처리
        if '\n' in value:
            value = PreservedScalarString(value)

        try:
            _set_value_by_path(data, path, sug_type, value)
        except Exception as e:
            print(f"[ApplyPatch-ERROR] 경로 '{path}' 적용 중 오류 발생: {e}")
            continue # 다음 제안으로 계속
            
    # ⭐️ 4. 수정된 YAML 데이터를 다시 문자열로 덤프
    try:
        with tempfile.NamedTemporaryFile(delete=False, mode='w') as f:
            yaml.dump(data, f)
            temp_path = f.name
        
        with open(temp_path, 'r') as f:
            final_yaml_str = f.read()
        
        os.remove(temp_path)
        return final_yaml_str
        
    except Exception as e:
        print(f"[ApplyPatch-ERROR] 최종 YAML 덤프 실패: {e}")
        return original_yaml