#!/usr/bin/env python3
"""MARA Agent Output Validator

각 Agent의 마크다운 출력을 contract YAML 스키마 대비 검증한다.

Usage:
    python src/validation/validate.py <agent_name> <output_file> [--contract-dir src/contracts/]

Exit codes:
    0 — PASS (errors 없음)
    1 — FAIL (errors 있음)
    2 — 실행 오류 (파일 없음, contract 파싱 실패 등)
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# YAML 파서 (PyYAML 의존 없이 간단한 YAML subset 지원)
# ---------------------------------------------------------------------------

def _parse_yaml_value(raw: str):
    """스칼라 값을 Python 타입으로 변환한다."""
    raw = raw.strip()
    if raw == "":
        return ""
    if raw in ("true", "True", "yes"):
        return True
    if raw in ("false", "False", "no"):
        return False
    if raw == "{}":
        return {}
    if raw == "[]":
        return []
    # 숫자
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        pass
    # 따옴표 제거
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw


def _indent_level(line: str) -> int:
    return len(line) - len(line.lstrip())


def parse_yaml(text: str) -> dict:
    """최소한의 YAML subset 파서. 중첩 dict, list, 스칼라를 지원한다."""
    lines = text.splitlines()
    return _parse_yaml_block(lines, 0, 0)[0]


def _parse_yaml_block(lines: list, start: int, base_indent: int) -> tuple:
    """(result_dict, next_line_index) 를 반환한다."""
    result = {}
    i = start
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 빈 줄, 주석 건너뛰기
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        indent = _indent_level(line)

        # 현재 블록보다 인덴트가 작으면 블록 종료
        if indent < base_indent:
            break

        # 리스트 항목
        if stripped.startswith("- "):
            # 부모가 dict이 아닌 list를 기대하는 경우
            # 이 함수는 dict 블록 파서이므로, list는 별도 처리
            break

        # key: value 파싱
        if ":" in stripped:
            colon_pos = stripped.index(":")
            key = stripped[:colon_pos].strip()
            value_part = stripped[colon_pos + 1:].strip()

            if value_part == "" or value_part == "|":
                # 다음 줄이 더 깊은 인덴트인지 확인
                next_indent = _peek_next_indent(lines, i + 1)
                if next_indent is not None and next_indent > indent:
                    # 다음 줄이 리스트인지 dict인지 확인
                    next_stripped = _peek_next_content(lines, i + 1)
                    if next_stripped and next_stripped.startswith("- "):
                        lst, i = _parse_yaml_list(lines, i + 1, next_indent)
                        result[key] = lst
                    else:
                        child, i = _parse_yaml_block(lines, i + 1, next_indent)
                        result[key] = child
                else:
                    result[key] = {} if value_part == "" else ""
                    i += 1
            else:
                # 인라인 list: [a, b, c]
                if value_part.startswith("[") and value_part.endswith("]"):
                    inner = value_part[1:-1]
                    if inner.strip() == "":
                        result[key] = []
                    else:
                        result[key] = [_parse_yaml_value(v) for v in inner.split(",")]
                else:
                    result[key] = _parse_yaml_value(value_part)
                i += 1
        else:
            i += 1

    return result, i


def _parse_yaml_list(lines: list, start: int, base_indent: int) -> tuple:
    """(result_list, next_line_index) 를 반환한다."""
    result = []
    i = start
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        indent = _indent_level(line)
        if indent < base_indent:
            break

        if stripped.startswith("- "):
            item_value = stripped[2:].strip()
            # 리스트 항목이 key: value를 포함하는지 확인
            if ":" in item_value:
                # 인라인 dict 또는 멀티라인 dict
                next_indent = _peek_next_indent(lines, i + 1)
                if next_indent is not None and next_indent > indent:
                    # 멀티라인 dict
                    colon_pos = item_value.index(":")
                    first_key = item_value[:colon_pos].strip()
                    first_val = item_value[colon_pos + 1:].strip()
                    child, new_i = _parse_yaml_block(lines, i + 1, next_indent)
                    child[first_key] = _parse_yaml_value(first_val) if first_val else child.get(first_key, "")
                    # first_key를 맨 앞에 배치
                    ordered = {first_key: child.pop(first_key, "")}
                    ordered.update(child)
                    result.append(ordered)
                    i = new_i
                else:
                    # 단순 key: value → dict로 변환하지 않고 문자열로
                    result.append(_parse_yaml_value(item_value))
                    i += 1
            else:
                result.append(_parse_yaml_value(item_value))
                i += 1
        else:
            break

    return result, i


def _peek_next_indent(lines: list, start: int):
    for j in range(start, len(lines)):
        s = lines[j].strip()
        if s and not s.startswith("#"):
            return _indent_level(lines[j])
    return None


def _peek_next_content(lines: list, start: int):
    for j in range(start, len(lines)):
        s = lines[j].strip()
        if s and not s.startswith("#"):
            return s
    return None


# ---------------------------------------------------------------------------
# 마크다운 파서
# ---------------------------------------------------------------------------

class MarkdownParser:
    """마크다운 텍스트에서 섹션과 테이블을 추출한다."""

    def __init__(self, text: str):
        self.text = text
        self.lines = text.splitlines()

    def get_sections(self) -> List[str]:
        """모든 H2/H3 섹션 제목을 반환한다."""
        sections = []
        for line in self.lines:
            stripped = line.strip()
            if stripped.startswith("## ") or stripped.startswith("### "):
                title = re.sub(r"^#{2,3}\s+", "", stripped)
                sections.append(title)
        return sections

    def find_section_content(self, section_name: str) -> Optional[str]:
        """주어진 섹션 제목 아래의 내용을 반환한다."""
        in_section = False
        section_level = 0
        content_lines = []

        for line in self.lines:
            stripped = line.strip()
            if stripped.startswith("## ") or stripped.startswith("### "):
                if in_section:
                    # 같거나 상위 레벨의 헤더를 만나면 종료
                    current_level = 3 if stripped.startswith("### ") else 2
                    if current_level <= section_level:
                        break
                title = re.sub(r"^#{2,3}\s+", "", stripped)
                if section_name in title:
                    in_section = True
                    section_level = 3 if stripped.startswith("### ") else 2
                    continue

            if in_section:
                content_lines.append(line)

        return "\n".join(content_lines) if content_lines else None

    def find_tables_in_section(self, section_name: str) -> List[dict]:
        """섹션 내의 마크다운 테이블을 파싱한다. [{columns: [...], rows: [...]}]"""
        content = self.find_section_content(section_name)
        if not content:
            return []
        return self._parse_tables(content)

    def find_all_tables(self) -> List[dict]:
        """전체 문서에서 모든 테이블을 파싱한다."""
        return self._parse_tables(self.text)

    def _parse_tables(self, text: str) -> List[dict]:
        """마크다운 테이블을 파싱한다."""
        tables = []
        lines = text.splitlines()
        i = 0

        while i < len(lines):
            line = lines[i].strip()
            # 테이블 헤더 감지: | col1 | col2 | ...
            if line.startswith("|") and i + 1 < len(lines):
                separator = lines[i + 1].strip()
                # 구분선 확인: |---|---|
                if separator.startswith("|") and re.match(r"\|[\s\-:]+\|", separator):
                    columns = [c.strip() for c in line.split("|") if c.strip()]
                    rows = []
                    j = i + 2
                    while j < len(lines):
                        row_line = lines[j].strip()
                        if not row_line.startswith("|"):
                            break
                        cells = [c.strip() for c in row_line.split("|") if c.strip()]
                        if cells:
                            row = {}
                            for k, col in enumerate(columns):
                                row[col] = cells[k] if k < len(cells) else ""
                            rows.append(row)
                        j += 1
                    tables.append({"columns": columns, "rows": rows})
                    i = j
                    continue
            i += 1

        return tables


# ---------------------------------------------------------------------------
# Contract 로더
# ---------------------------------------------------------------------------

class ContractLoader:
    """YAML contract 파일을 로드하고 상속을 처리한다."""

    def __init__(self, contract_dir: str):
        self.contract_dir = Path(contract_dir)

    def load(self, agent_name: str) -> dict:
        """agent_name에 해당하는 contract를 로드한다. inherits가 있으면 병합한다."""
        path = self.contract_dir / f"{agent_name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Contract 파일을 찾을 수 없습니다: {path}")

        with open(path, "r", encoding="utf-8") as f:
            contract = parse_yaml(f.read())

        # 상속 처리
        if "inherits" in contract:
            parent = self.load(contract["inherits"])
            contract = self._merge(parent, contract)

        return contract

    def _merge(self, parent: dict, child: dict) -> dict:
        """parent contract 위에 child를 병합한다."""
        merged = {}

        # 스칼라 필드는 child 우선
        for key in ("name", "description", "output_path"):
            merged[key] = child.get(key, parent.get(key, ""))

        # required_sections: 합집합
        parent_sections = parent.get("required_sections", [])
        child_sections = child.get("required_sections", [])
        merged["required_sections"] = list(dict.fromkeys(parent_sections + child_sections))

        # required_fields: 병합
        parent_fields = parent.get("required_fields", {})
        child_fields = child.get("required_fields", {})
        merged["required_fields"] = {**parent_fields, **child_fields}

        # required_tables: 병합
        parent_tables = parent.get("required_tables", {})
        child_tables = child.get("required_tables", {})
        merged["required_tables"] = {**parent_tables, **child_tables}

        return merged


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class AgentValidator:
    """Agent 출력을 contract 대비 검증한다."""

    def __init__(self, contract: dict):
        self.contract = contract
        self.errors: list[dict] = []
        self.warnings: list[dict] = []

    def validate(self, markdown_text: str) -> dict:
        """전체 검증을 수행하고 결과를 반환한다."""
        self.errors = []
        self.warnings = []

        parser = MarkdownParser(markdown_text)

        self._validate_sections(parser)
        self._validate_fields(markdown_text)
        self._validate_tables(parser)

        status = "PASS" if not self.errors else "FAIL"
        return {
            "agent": self.contract.get("name", "unknown"),
            "status": status,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def _validate_sections(self, parser: MarkdownParser):
        """필수 섹션 존재 여부를 검증한다."""
        existing = parser.get_sections()
        required = self.contract.get("required_sections", [])

        for section in required:
            found = any(section in s for s in existing)
            if not found:
                self.errors.append({
                    "type": "missing_section",
                    "detail": f"'{section}' 섹션이 없습니다",
                })

    def _validate_fields(self, text: str):
        """필수 필드의 값을 검증한다."""
        fields = self.contract.get("required_fields", {})
        if not fields or isinstance(fields, str):
            return

        for field_name, spec in fields.items():
            if not isinstance(spec, dict):
                continue

            pattern = spec.get("pattern", "")
            if not pattern:
                continue

            flags = re.IGNORECASE if spec.get("case_insensitive") else 0
            match = re.search(pattern, text, flags)

            if not match:
                self.errors.append({
                    "type": "missing_field",
                    "detail": f"'{field_name}' 필드를 찾을 수 없습니다 (패턴: {pattern})",
                })
                continue

            value = match.group(1)
            field_type = spec.get("type", "")

            if field_type == "enum":
                allowed = spec.get("values", [])
                check_val = value.lower() if spec.get("case_insensitive") else value
                allowed_check = [v.lower() for v in allowed] if spec.get("case_insensitive") else allowed
                if check_val not in allowed_check:
                    self.errors.append({
                        "type": "invalid_field",
                        "detail": f"'{field_name}' 값 '{value}'이(가) 허용 목록 {allowed}에 없습니다",
                    })

            elif field_type == "float" or field_type == "percentage":
                try:
                    num = float(value.rstrip("%"))
                    # percentage 타입은 0-100% 범위도 허용
                    if field_type == "percentage" and num > 1.0:
                        num = num / 100.0
                    min_val = spec.get("min", float("-inf"))
                    max_val = spec.get("max", float("inf"))
                    if num < min_val or num > max_val:
                        self.errors.append({
                            "type": "invalid_field",
                            "detail": f"'{field_name}' 값 {value}이(가) 범위({min_val}-{max_val})를 벗어났습니다",
                        })
                except ValueError:
                    self.errors.append({
                        "type": "invalid_field",
                        "detail": f"'{field_name}' 값 '{value}'이(가) 숫자가 아닙니다",
                    })

    def _validate_tables(self, parser: MarkdownParser):
        """필수 테이블의 컬럼과 값 제약을 검증한다."""
        tables_spec = self.contract.get("required_tables", {})
        if not tables_spec or isinstance(tables_spec, str):
            return

        for table_name, spec in tables_spec.items():
            if not isinstance(spec, dict):
                continue

            section = spec.get("section", "")
            required_columns = spec.get("required_columns", [])

            # 섹션 내 테이블 찾기
            if section:
                tables = parser.find_tables_in_section(section)
            else:
                tables = parser.find_all_tables()

            if not tables:
                self.errors.append({
                    "type": "missing_table",
                    "detail": f"'{table_name}' 테이블을 '{section}' 섹션에서 찾을 수 없습니다",
                })
                continue

            # 첫 번째 매칭 테이블 사용
            table = tables[0]

            # 컬럼 존재 확인
            for col in required_columns:
                if col not in table["columns"]:
                    self.errors.append({
                        "type": "missing_column",
                        "detail": f"'{table_name}' 테이블에 '{col}' 컬럼이 없습니다",
                    })

            # 빈 테이블 경고
            if not table["rows"]:
                self.warnings.append({
                    "type": "empty_table",
                    "detail": f"'{table_name}' 테이블에 데이터 행이 없습니다",
                })
                continue

            # 행 값 제약 검증
            row_constraints = spec.get("row_constraints", {})
            if not row_constraints or not isinstance(row_constraints, dict):
                continue

            for row_idx, row in enumerate(table["rows"]):
                for col_name, constraint in row_constraints.items():
                    if not isinstance(constraint, dict):
                        continue
                    if col_name not in row:
                        continue

                    cell_value = row[col_name]
                    c_type = constraint.get("type", "")

                    if c_type == "enum":
                        allowed = constraint.get("values", [])
                        if cell_value not in allowed:
                            self.errors.append({
                                "type": "invalid_cell",
                                "detail": f"'{table_name}' 행 {row_idx + 1}, '{col_name}' 값 '{cell_value}'이(가) 허용 목록 {allowed}에 없습니다",
                            })

                    elif c_type == "float" or c_type == "percentage":
                        try:
                            num = float(cell_value.rstrip("%"))
                            if c_type == "percentage" and num > 1.0:
                                num = num / 100.0
                            min_val = constraint.get("min", float("-inf"))
                            max_val = constraint.get("max", float("inf"))
                            if num < min_val or num > max_val:
                                self.errors.append({
                                    "type": "invalid_cell",
                                    "detail": f"'{table_name}' 행 {row_idx + 1}, '{col_name}' 값 {cell_value}이(가) 범위({min_val}-{max_val})를 벗어났습니다",
                                })
                        except ValueError:
                            self.warnings.append({
                                "type": "parse_warning",
                                "detail": f"'{table_name}' 행 {row_idx + 1}, '{col_name}' 값 '{cell_value}'을(를) 숫자로 파싱할 수 없습니다",
                            })


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="MARA Agent Output Validator")
    parser.add_argument("agent_name", help="Agent 이름 (contract 파일명과 동일)")
    parser.add_argument("output_file", help="검증할 마크다운 출력 파일 경로")
    parser.add_argument(
        "--contract-dir",
        default=None,
        help="Contract YAML 디렉토리 (기본: src/contracts/)",
    )
    args = parser.parse_args()

    # contract 디렉토리 결정
    if args.contract_dir:
        contract_dir = args.contract_dir
    else:
        # 스크립트 위치 기준으로 contracts 디렉토리 찾기
        script_dir = Path(__file__).parent
        contract_dir = script_dir.parent / "contracts"
        if not contract_dir.exists():
            # cwd 기준
            contract_dir = Path("src/contracts")

    # 출력 파일 읽기
    output_path = Path(args.output_file)
    if not output_path.exists():
        print(json.dumps({
            "agent": args.agent_name,
            "status": "ERROR",
            "errors": [{"type": "file_not_found", "detail": f"출력 파일을 찾을 수 없습니다: {args.output_file}"}],
            "warnings": [],
        }, ensure_ascii=False, indent=2))
        sys.exit(2)

    with open(output_path, "r", encoding="utf-8") as f:
        markdown_text = f.read()

    # Contract 로드
    try:
        loader = ContractLoader(str(contract_dir))
        contract = loader.load(args.agent_name)
    except FileNotFoundError as e:
        print(json.dumps({
            "agent": args.agent_name,
            "status": "ERROR",
            "errors": [{"type": "contract_not_found", "detail": str(e)}],
            "warnings": [],
        }, ensure_ascii=False, indent=2))
        sys.exit(2)

    # 검증 실행
    validator = AgentValidator(contract)
    result = validator.validate(markdown_text)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
