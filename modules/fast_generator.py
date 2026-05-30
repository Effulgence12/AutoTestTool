from __future__ import annotations

import csv
import io
import re
from typing import Any

from .schema import normalize_result


ID_COLUMNS = ("req_id", "requirement_id", "id")
TEXT_COLUMNS = ("description", "raw_text", "requirement", "requirements", "text")
PRIORITY_COLUMNS = ("priority", "test_priority")


def generate_fast_result(
    target_app: str,
    target_module: str,
    requirements_text: str,
) -> dict[str, Any]:
    requirement_sources = parse_requirement_sources(requirements_text)
    result = {
        "project": {
            "target_app": target_app.strip() or "Unnamed target application",
            "target_module": target_module.strip() or "Main module",
            "concept": "Fast local rule-based test design with AI enhancement available.",
            "prompt_design_notes": (
                "Fast mode does not call a remote LLM. It parses imported requirements "
                "locally, applies risk heuristics, generates EP/BVA/DT cases, and then "
                "passes the result through the shared rule engine."
            ),
        },
        "requirements": [],
        "risks": [],
        "coverage_items": [],
        "strategies": [],
        "test_cases": [],
        "traceability": [],
        "white_box_model": [],
        "optimization_summary": "",
        "result_analysis": "",
    }

    counters = {"CI": 0, "ST": 0, "TC": 0}
    for index, source in enumerate(requirement_sources, start=1):
        requirement = structure_requirement(source, index)
        result["requirements"].append(requirement)
        result["risks"].append(score_requirement(requirement, source.get("priority", "")))
        add_equivalence_case(result, requirement, counters)
        for range_item in extract_ranges(requirement["raw_text"]):
            add_boundary_case(result, requirement, range_item, counters)
        if should_add_decision_table(requirement):
            add_decision_table_case(result, requirement, counters)

    ensure_required_black_box_techniques(result, counters)
    add_white_box_summary(result)
    result["optimization_summary"] = (
        "Fast mode assigns execution priority from local risk score, priority, "
        "boundary coverage, and traceability coverage. Detailed ranks are added by "
        "the shared rule engine."
    )
    result["result_analysis"] = (
        "Generated locally from imported requirements: each requirement receives "
        "structured fields, a risk row, at least one coverage strategy, test cases, "
        "and traceability. Qwen can be used afterward for richer explanation."
    )
    return normalize_result(result)


def parse_requirement_sources(requirements_text: str) -> list[dict[str, str]]:
    csv_rows, consumed_lines = parse_csv_sections(requirements_text)
    plain_rows = parse_plain_text_requirements(requirements_text, consumed_lines, csv_rows)
    rows = csv_rows + plain_rows
    if rows:
        return rows
    text = requirements_text.strip()
    if not text:
        return []
    return [{"requirement_id": "REQ-001", "raw_text": text, "priority": ""}]


def parse_csv_sections(requirements_text: str) -> tuple[list[dict[str, str]], set[int]]:
    lines = requirements_text.splitlines()
    rows: list[dict[str, str]] = []
    consumed: set[int] = set()
    index = 0
    while index < len(lines):
        header = parse_csv_line(lines[index])
        column_map = columns_for(header)
        if column_map is None:
            if is_csv_metadata_line(lines[index]):
                consumed.add(index)
            index += 1
            continue

        block_lines = [lines[index]]
        block_indices = {index}
        cursor = index + 1
        while cursor < len(lines):
            line = lines[cursor]
            if not line.strip() or line.startswith("CSV file:"):
                break
            block_lines.append(line)
            block_indices.add(cursor)
            cursor += 1

        rows.extend(read_csv_block(block_lines, column_map))
        consumed.update(block_indices)
        index = cursor

    return rows, consumed


def parse_csv_line(line: str) -> list[str]:
    try:
        return next(csv.reader([line]))
    except csv.Error:
        return []


def columns_for(header: list[str]) -> dict[str, str] | None:
    normalized = {column.strip().lower(): column for column in header}
    id_column = next((normalized[name] for name in ID_COLUMNS if name in normalized), "")
    text_column = next(
        (normalized[name] for name in TEXT_COLUMNS if name in normalized),
        "",
    )
    priority_column = next(
        (normalized[name] for name in PRIORITY_COLUMNS if name in normalized),
        "",
    )
    if not id_column or not text_column:
        return None
    return {"id": id_column, "text": text_column, "priority": priority_column}


def read_csv_block(block_lines: list[str], column_map: dict[str, str]) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO("\n".join(block_lines)))
    rows: list[dict[str, str]] = []
    for index, row in enumerate(reader, start=1):
        requirement_id = str(row.get(column_map["id"], "")).strip()
        raw_text = str(row.get(column_map["text"], "")).strip()
        if not requirement_id or not raw_text:
            continue
        priority = str(row.get(column_map.get("priority", ""), "")).strip()
        rows.append(
            {
                "requirement_id": requirement_id,
                "raw_text": raw_text,
                "priority": priority,
                "source": "csv",
                "source_index": str(index),
            }
        )
    return rows


def is_csv_metadata_line(line: str) -> bool:
    prefixes = (
        "CSV file:",
        "CSV requirement row count:",
        "Required requirement_id values",
        "CSV parsing rule:",
    )
    return line.strip().startswith(prefixes)


def parse_plain_text_requirements(
    requirements_text: str,
    consumed_lines: set[int],
    csv_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    plain_parts: list[str] = []
    for index, line in enumerate(requirements_text.splitlines()):
        if index in consumed_lines or is_csv_metadata_line(line):
            continue
        stripped = line.strip()
        if stripped:
            plain_parts.append(stripped)
    text = "\n".join(plain_parts).strip()
    if not text:
        return []

    pieces: list[str] = []
    for line in text.splitlines():
        stripped = re.sub(r"^\s*[-*•]|\s*\d+[.)、]\s*", "", line).strip()
        if not stripped:
            continue
        if len(stripped) > 80:
            pieces.extend(split_sentences(stripped))
        else:
            pieces.append(stripped)

    existing_ids = {row["requirement_id"] for row in csv_rows}
    rows: list[dict[str, str]] = []
    number = 1
    for piece in pieces:
        if not piece:
            continue
        while f"REQ-{number:03d}" in existing_ids:
            number += 1
        requirement_id = f"REQ-{number:03d}"
        rows.append(
            {
                "requirement_id": requirement_id,
                "raw_text": piece,
                "priority": "",
                "source": "plain_text",
                "source_index": str(number),
            }
        )
        existing_ids.add(requirement_id)
        number += 1
    return rows


def split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"[。；;]\s*", text) if part.strip()]
    return parts or [text.strip()]


def structure_requirement(source: dict[str, str], index: int) -> dict[str, str]:
    raw_text = source["raw_text"]
    fields = extract_fields(raw_text)
    ranges = extract_ranges(raw_text)
    conditions = extract_conditions(raw_text)
    actions = extract_expected_actions(raw_text)
    return {
        "requirement_id": source.get("requirement_id") or f"REQ-{index:03d}",
        "raw_text": raw_text,
        "input_fields": "; ".join(fields) if fields else "Input",
        "data_ranges": "; ".join(range_item["description"] for range_item in ranges),
        "conditions": "; ".join(conditions),
        "expected_actions": "; ".join(actions) or "System handles the input according to the requirement.",
    }


def extract_fields(text: str) -> list[str]:
    field_patterns = [
        ("Username", r"username|user name|用户名"),
        ("Password", r"password|pwd|密码"),
        ("Email", r"email|邮箱"),
        ("Session", r"session|会话"),
        ("Token", r"token|令牌"),
        ("Account", r"account|账户|账号"),
        ("Verification Code", r"验证码|verification code"),
    ]
    fields = [name for name, pattern in field_patterns if re.search(pattern, text, re.I)]
    return dedupe(fields)


def extract_ranges(text: str) -> list[dict[str, str]]:
    ranges: list[dict[str, str]] = []
    for match in re.finditer(r"(-?\d+)\s*(?:到|至|-|~|to)\s*(-?\d+)\s*(个字符|字符|位|分钟|次|attempts?|minutes?)?", text, re.I):
        low, high = int(match.group(1)), int(match.group(2))
        if low > high:
            low, high = high, low
        unit = normalize_unit(match.group(3) or "")
        field = infer_field_near(text, match.start())
        ranges.append(
            {
                "field": field,
                "low": str(low),
                "high": str(high),
                "unit": unit,
                "description": f"{field}: {low}-{high} {unit}".strip(),
            }
        )

    threshold_patterns = [
        (r"(?:至少|不小于|minimum|at least)\s*(-?\d+)\s*(个字符|字符|位|分钟|次|attempts?|minutes?)?", ">="),
        (r"(?:超过|大于|more than|greater than)\s*(-?\d+)\s*(个字符|字符|位|分钟|次|attempts?|minutes?)?", ">"),
        (r"(?:不超过|至多|maximum|at most)\s*(-?\d+)\s*(个字符|字符|位|分钟|次|attempts?|minutes?)?", "<="),
    ]
    for pattern, operator in threshold_patterns:
        for match in re.finditer(pattern, text, re.I):
            value = int(match.group(1))
            unit = normalize_unit(match.group(2) or "")
            field = infer_field_near(text, match.start())
            ranges.append(
                {
                    "field": field,
                    "low": str(value),
                    "high": str(value),
                    "unit": unit,
                    "description": f"{field}: {operator}{value} {unit}".strip(),
                }
            )
    return dedupe_ranges(ranges)


def normalize_unit(unit: str) -> str:
    if unit in {"个字符", "字符", "位"}:
        return "chars"
    if unit in {"次", "attempt", "attempts"}:
        return "attempts"
    if unit in {"分钟", "minute", "minutes"}:
        return "minutes"
    return unit.strip()


def infer_field_near(text: str, position: int) -> str:
    window = text[max(0, position - 24) : position + 24].lower()
    if re.search(r"username|user name|用户名", window):
        return "Username"
    if re.search(r"password|pwd|密码", window):
        return "Password"
    if re.search(r"email|邮箱", window):
        return "Email"
    if re.search(r"失败|错误|failure|attempt", window):
        return "Failure Count"
    if re.search(r"锁定|lock|分钟|minute", window):
        return "Lock Duration"
    return "Input"


def extract_conditions(text: str) -> list[str]:
    conditions: list[str] = []
    for match in re.finditer(r"(?:如果|若|when|if)\s*(.{2,80}?)(?:则|那么|,|，|should|must)", text, re.I):
        conditions.append(match.group(1).strip())
    keyword_conditions = [
        ("Username is empty", r"用户名不能为空|username.*not.*empty|username.*required"),
        ("Password is empty", r"密码不能为空|password.*not.*empty|password.*required"),
        ("Email format is valid", r"邮箱.*格式|valid email|email format"),
        ("Two passwords match", r"两次.*密码.*一致|passwords? match"),
        ("Username is already occupied", r"用户名.*占用|已被占用|already.*taken"),
        ("User does not exist or password is wrong", r"用户不存在|密码错误|wrong password|user.*not.*exist"),
        ("Account is locked", r"锁定|locked"),
        ("Session is missing or expired", r"未登录|会话失效|unauthorized|session.*expired"),
        ("Token is invalid or expired", r"无效.*令牌|过期.*令牌|invalid.*token|expired.*token"),
    ]
    for label, pattern in keyword_conditions:
        if re.search(pattern, text, re.I):
            conditions.append(label)
    return dedupe(conditions)


def extract_expected_actions(text: str) -> list[str]:
    actions: list[str] = []
    action_patterns = [
        ("Reject the operation and show validation error.", r"拒绝|失败|错误提示|返回未授权|unauthorized|reject"),
        ("Create an authenticated session.", r"建立会话|登录成功|create session|login success"),
        ("Lock the account for the required duration.", r"锁定.*账户|account.*locked"),
        ("Clear the session after logout.", r"登出|logout|会话.*清除"),
        ("Reset password when token and new password are valid.", r"重置密码|password reset"),
        ("Return the current user's profile data.", r"个人资料|profile"),
    ]
    for label, pattern in action_patterns:
        if re.search(pattern, text, re.I):
            actions.append(label)
    return dedupe(actions)


def score_requirement(requirement: dict[str, str], source_priority: str) -> dict[str, str]:
    text = " ".join(requirement.values()).lower()
    score = 30
    reasons: list[str] = []

    if re.search(r"password|密码|token|令牌|session|会话|lock|锁|unauthorized|权限", text):
        score += 25
        reasons.append("authentication/security/session semantics")
    if requirement.get("conditions"):
        count = len([part for part in requirement["conditions"].split(";") if part.strip()])
        score += min(20, count * 5)
        reasons.append(f"{count} condition branch(es)")
    if requirement.get("data_ranges"):
        count = len([part for part in requirement["data_ranges"].split(";") if part.strip()])
        score += min(15, count * 5)
        reasons.append(f"{count} data range or threshold constraint(s)")

    priority_hint = source_priority.strip().lower()
    if priority_hint == "high":
        score += 15
        reasons.append("source CSV priority is High")
    elif priority_hint == "low":
        score -= 8
        reasons.append("source CSV priority is Low")

    score = max(0, min(100, score))
    if score >= 70:
        priority = "High"
    elif score >= 40:
        priority = "Medium"
    else:
        priority = "Low"

    return {
        "requirement_id": requirement["requirement_id"],
        "risk_score": str(score),
        "priority": priority,
        "reason": "; ".join(reasons) or "Baseline local risk model.",
    }


def add_equivalence_case(
    result: dict[str, Any],
    requirement: dict[str, str],
    counters: dict[str, int],
) -> None:
    coverage_id = next_counter("CI", counters)
    strategy_id = next_counter("ST", counters)
    test_case_id = next_counter("TC", counters)
    fields = requirement["input_fields"] or "Input"
    result["coverage_items"].append(
        {
            "coverage_item_id": coverage_id,
            "requirement_id": requirement["requirement_id"],
            "coverage_item": f"{fields} valid and invalid equivalence classes",
            "type": "Input Field",
            "rationale": "Local EP rule covers representative valid and invalid input classes.",
        }
    )
    result["strategies"].append(
        {
            "strategy_id": strategy_id,
            "coverage_item_id": coverage_id,
            "technique": "Equivalence Partitioning",
            "method": f"Partition {fields} into valid and invalid classes.",
            "rationale": "Equivalence classes reduce redundant input combinations while preserving behavior coverage.",
        }
    )
    add_test_case(
        result,
        requirement,
        strategy_id,
        test_case_id,
        "Equivalence Partitioning",
        representative_test_data(requirement, valid=True),
        "1. Prepare representative valid and invalid input classes. 2. Execute the target behavior. 3. Compare the observed result with the requirement.",
        requirement["expected_actions"],
        "Fast Rule-Based EP",
        coverage_id,
    )


def add_boundary_case(
    result: dict[str, Any],
    requirement: dict[str, str],
    range_item: dict[str, str],
    counters: dict[str, int],
) -> None:
    coverage_id = next_counter("CI", counters)
    strategy_id = next_counter("ST", counters)
    test_case_id = next_counter("TC", counters)
    low = safe_int(range_item["low"])
    high = safe_int(range_item["high"])
    probe = str(low - 1 if low == high else low)
    field = range_item["field"]
    result["coverage_items"].append(
        {
            "coverage_item_id": coverage_id,
            "requirement_id": requirement["requirement_id"],
            "coverage_item": f"{field} boundary around {range_item['description']}",
            "type": "Data Range",
            "rationale": "Local BVA rule targets values at and near the stated limit.",
        }
    )
    result["strategies"].append(
        {
            "strategy_id": strategy_id,
            "coverage_item_id": coverage_id,
            "technique": "Boundary Value Analysis",
            "method": f"Test {field} near {range_item['description']}.",
            "rationale": "Defects often occur at the edge of accepted ranges and thresholds.",
        }
    )
    expected = (
        f"System accepts {field} at boundary {probe} if it satisfies {range_item['description']}; otherwise it rejects with a validation error."
    )
    add_test_case(
        result,
        requirement,
        strategy_id,
        test_case_id,
        "Boundary Value Analysis",
        boundary_test_data(requirement, field, probe),
        "1. Prepare all required fields. 2. Set the boundary field to the stated value. 3. Submit or execute the operation.",
        expected,
        "Fast Rule-Based BVA",
        coverage_id,
    )


def add_decision_table_case(
    result: dict[str, Any],
    requirement: dict[str, str],
    counters: dict[str, int],
) -> None:
    coverage_id = next_counter("CI", counters)
    strategy_id = next_counter("ST", counters)
    test_case_id = next_counter("TC", counters)
    conditions = requirement["conditions"] or "Requirement decision conditions"
    result["coverage_items"].append(
        {
            "coverage_item_id": coverage_id,
            "requirement_id": requirement["requirement_id"],
            "coverage_item": f"Decision outcomes for {conditions}",
            "type": "Decision",
            "rationale": "Local DT rule covers condition/action combinations.",
        }
    )
    result["strategies"].append(
        {
            "strategy_id": strategy_id,
            "coverage_item_id": coverage_id,
            "technique": "Decision Table",
            "method": f"Evaluate condition/action combinations: {conditions}.",
            "rationale": "Decision tables make multi-condition behavior explicit and traceable.",
        }
    )
    add_test_case(
        result,
        requirement,
        strategy_id,
        test_case_id,
        "Decision Table",
        decision_table_data(requirement),
        "1. Set each decision condition as specified in test_data. 2. Execute the operation. 3. Verify the expected action row.",
        f"Decision table action follows requirement: {requirement['expected_actions']}",
        "Fast Rule-Based DT",
        coverage_id,
    )


def should_add_decision_table(requirement: dict[str, str]) -> bool:
    conditions = [part for part in requirement.get("conditions", "").split(";") if part.strip()]
    return len(conditions) >= 2 or any(
        keyword in requirement["raw_text"]
        for keyword in ["若", "如果", "同时", "且", "或", "invalid", "expired"]
    )


def ensure_required_black_box_techniques(
    result: dict[str, Any], counters: dict[str, int]
) -> None:
    if not result["requirements"]:
        return
    text = " | ".join(row["technique"] for row in result["test_cases"]).lower()
    first_requirement = result["requirements"][0]
    if "boundary" not in text:
        add_boundary_case(
            result,
            first_requirement,
            {"field": "Input", "low": "0", "high": "1", "unit": "", "description": "Input: 0-1"},
            counters,
        )
    text = " | ".join(row["technique"] for row in result["test_cases"]).lower()
    if "decision" not in text:
        add_decision_table_case(result, first_requirement, counters)


def add_test_case(
    result: dict[str, Any],
    requirement: dict[str, str],
    strategy_id: str,
    test_case_id: str,
    technique: str,
    test_data: str,
    steps: str,
    expected_result: str,
    source: str,
    coverage_id: str,
) -> None:
    risk = next(
        (
            row
            for row in result["risks"]
            if row.get("requirement_id") == requirement["requirement_id"]
        ),
        {"priority": "Medium", "risk_score": "50"},
    )
    result["test_cases"].append(
        {
            "test_case_id": test_case_id,
            "requirement_id": requirement["requirement_id"],
            "strategy_id": strategy_id,
            "technique": technique,
            "test_data": test_data,
            "steps": steps,
            "expected_result": expected_result,
            "priority": risk.get("priority", "Medium"),
            "risk_score": risk.get("risk_score", "50"),
            "source": source,
            "optimization_rank": "",
            "optimization_reason": "",
        }
    )
    result["traceability"].append(
        {
            "requirement_id": requirement["requirement_id"],
            "coverage_item_id": coverage_id,
            "strategy_id": strategy_id,
            "test_case_id": test_case_id,
        }
    )


def representative_test_data(requirement: dict[str, str], *, valid: bool) -> str:
    fields = [field.strip() for field in requirement["input_fields"].split(";") if field.strip()]
    if not fields:
        fields = ["Input"]
    values = []
    for field in fields:
        values.append(f"{field} = {baseline_value(field) if valid else invalid_value(field)}")
    return "; ".join(values)


def boundary_test_data(requirement: dict[str, str], field: str, value: str) -> str:
    fields = [item.strip() for item in requirement["input_fields"].split(";") if item.strip()]
    if not fields:
        fields = [field]
    parts = []
    for item in fields:
        if item.lower() == field.lower():
            parts.append(f"{item} = {boundary_value(item, value)}")
        else:
            parts.append(f"{item} = {baseline_value(item)}")
    return "; ".join(parts)


def decision_table_data(requirement: dict[str, str]) -> str:
    conditions = [part.strip() for part in requirement["conditions"].split(";") if part.strip()]
    if not conditions:
        conditions = ["Primary condition"]
    assignments = [
        f"C{index}=True ({condition})"
        for index, condition in enumerate(conditions[:4], start=1)
    ]
    return "; ".join(assignments)


def baseline_value(field: str) -> str:
    lower = field.lower()
    if "username" in lower:
        return "'valid_user'"
    if "password" in lower:
        return "'ValidPass1'"
    if "email" in lower:
        return "'user@example.com'"
    if "token" in lower:
        return "'valid-token'"
    if "session" in lower:
        return "'valid-session'"
    return "'valid'"


def invalid_value(field: str) -> str:
    lower = field.lower()
    if "username" in lower:
        return "''"
    if "password" in lower:
        return "''"
    if "email" in lower:
        return "'invalid-email'"
    if "token" in lower:
        return "'expired-token'"
    if "session" in lower:
        return "None"
    return "''"


def boundary_value(field: str, value: str) -> str:
    lower = field.lower()
    if "username" in lower or "password" in lower:
        length = safe_int(value)
        if length <= 0:
            return "''"
        seed = "ValidPass1" if "password" in lower else "validuser"
        return "'" + (seed * ((length // len(seed)) + 1))[:length] + f"' (length {length})"
    return value


def add_white_box_summary(result: dict[str, Any]) -> None:
    if not result["requirements"]:
        return
    transitions = [f"{row['requirement_id']} decision path" for row in result["requirements"]]
    result["white_box_model"] = [
        {
            "model_type": "Decision Flow",
            "model_description": "Local fast mode models each structured requirement as a decision/action path.",
            "coverage_criterion": "Branch Coverage",
            "optimal_sequence": " -> ".join(transitions),
            "rationale": "Execute high-risk and decision-heavy paths first, then complete remaining requirement paths.",
        }
    ]


def next_counter(prefix: str, counters: dict[str, int]) -> str:
    counters[prefix] += 1
    return f"{prefix}-{counters[prefix]:03d}"


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def dedupe_ranges(ranges: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str, str]] = set()
    output: list[dict[str, str]] = []
    for item in ranges:
        key = (item["field"], item["low"], item["high"], item["unit"])
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def safe_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
