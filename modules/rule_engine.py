from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


def enrich_with_rule_engine(result: dict[str, Any]) -> dict[str, Any]:
    enriched = deepcopy(result)
    suggestions = generate_boundary_suggestions(enriched)
    enriched["rule_suggestions"] = suggestions
    apply_boundary_suggestions(enriched, suggestions)
    repair_missing_design_links(enriched)
    optimize_test_suite(enriched)
    build_state_model(enriched)
    return enriched


def generate_boundary_suggestions(result: dict[str, Any]) -> list[dict[str, str]]:
    suggestions: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for requirement in result.get("requirements", []):
        requirement_id = requirement.get("requirement_id", "")
        text = " ".join(
            [
                requirement.get("raw_text", ""),
                requirement.get("input_fields", ""),
                requirement.get("data_ranges", ""),
                requirement.get("conditions", ""),
                requirement.get("expected_actions", ""),
            ]
        )
        for field, boundary_text in boundary_texts_by_field(requirement, text):
            for value, source_rule, rationale in boundary_values_from_text(boundary_text):
                key = (requirement_id, field, value)
                if key in seen:
                    continue
                seen.add(key)
                suggestions.append(
                    {
                        "suggestion_id": f"RS-{len(suggestions) + 1:03d}",
                        "requirement_id": requirement_id,
                        "field": field,
                        "boundary_value": value,
                        "source_rule": source_rule,
                        "rationale": rationale,
                        "status": "Pending",
                    }
                )

    return suggestions


def boundary_texts_by_field(
    requirement: dict[str, str], fallback_text: str
) -> list[tuple[str, str]]:
    fields = split_input_fields(requirement.get("input_fields", ""))
    data_ranges = requirement.get("data_ranges", "")
    segments = [
        segment.strip()
        for segment in re.split(r"[;；。.\n\r]+", data_ranges)
        if segment.strip()
    ]
    field_texts: list[tuple[str, str]] = []
    for segment in segments:
        field = field_named_in_text(segment, fields)
        if field and boundary_values_from_text(segment):
            field_texts.append((field, segment))

    if field_texts:
        return field_texts

    field = infer_field_name(requirement)
    return [(field, fallback_text)]


def field_named_in_text(segment: str, fields: list[str]) -> str:
    segment_key = segment.lower()
    for field in fields:
        canonical = canonical_field_name(field)
        display = display_field_name(field).lower()
        if canonical and canonical in segment_key:
            return display_field_name(field)
        if display and display in segment_key:
            return display_field_name(field)
    if "username" in segment_key or "用户名" in segment_key:
        return "Username"
    if "password" in segment_key or "密码" in segment_key:
        return "Password"
    if "score" in segment_key or "成绩" in segment_key or "分数" in segment_key:
        return "Score"
    if "email" in segment_key or "邮箱" in segment_key:
        return "Email"
    return ""


def boundary_values_from_text(text: str) -> list[tuple[str, str, str]]:
    values: list[tuple[int, str, str]] = []

    for match in re.finditer(r"(?<!\d)(-?\d+)\s*(?:-|~|–|至|到|to)\s*(-?\d+)(?!\d)", text, flags=re.IGNORECASE):
        low, high = int(match.group(1)), int(match.group(2))
        if low > high:
            low, high = high, low
        for value in [low - 1, low, low + 1, high - 1, high, high + 1]:
            values.append((value, f"range {low}-{high}", f"覆盖范围 {low}-{high} 的边界值 {value}。"))

    threshold_patterns = [
        r"(?:>=|≥|至少|不小于|不低于|大于等于|minimum|at least)\s*(-?\d+)",
        r"(?:<=|≤|至多|不超过|不高于|小于等于|maximum|at most)\s*(-?\d+)",
        r"(?:pass|及格|excellent|优秀|grade|等级)[^\d-]{0,12}(-?\d+)",
    ]
    for pattern in threshold_patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            threshold = int(match.group(1))
            for value in [threshold - 1, threshold, threshold + 1]:
                values.append(
                    (
                        value,
                        f"threshold {threshold}",
                        f"覆盖阈值 {threshold} 附近的边界值 {value}。",
                    )
                )

    deduped: list[tuple[str, str, str]] = []
    seen: set[int] = set()
    for value, source_rule, rationale in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append((str(value), source_rule, rationale))
    return deduped


def infer_field_name(requirement: dict[str, str]) -> str:
    fields = requirement.get("input_fields", "").strip()
    if fields:
        return fields.split(";")[0].split(",")[0].strip()
    text = requirement.get("raw_text", "").lower()
    if "score" in text or "成绩" in text or "分数" in text:
        return "score"
    if "username" in text or "用户名" in text:
        return "username"
    if "password" in text or "密码" in text:
        return "password"
    return "input"


def apply_boundary_suggestions(result: dict[str, Any], suggestions: list[dict[str, str]]) -> None:
    existing_test_values = " | ".join(
        test_case.get("test_data", "") for test_case in result.get("test_cases", [])
    )
    existing_coverage_text = " | ".join(
        item.get("coverage_item", "") for item in result.get("coverage_items", [])
    )

    coverage_ids = {row.get("coverage_item_id", "") for row in result.get("coverage_items", [])}
    coverage_ids.update(row.get("coverage_item_id", "") for row in result.get("traceability", []))
    strategy_ids = {row.get("strategy_id", "") for row in result.get("strategies", [])}
    strategy_ids.update(row.get("strategy_id", "") for row in result.get("test_cases", []))
    strategy_ids.update(row.get("strategy_id", "") for row in result.get("traceability", []))
    test_case_ids = {row.get("test_case_id", "") for row in result.get("test_cases", [])}

    for suggestion in suggestions:
        requirement_id = suggestion["requirement_id"]
        value = suggestion["boundary_value"]
        field = suggestion["field"]
        if value_present(existing_test_values, value) and value_present(existing_coverage_text, value):
            suggestion["status"] = "Already Covered"
            continue

        coverage_id = next_id("CI", coverage_ids)
        strategy_id = next_id("ST", strategy_ids)
        test_case_id = next_id("TC", test_case_ids)
        coverage_ids.add(coverage_id)
        strategy_ids.add(strategy_id)
        test_case_ids.add(test_case_id)

        result.setdefault("coverage_items", []).append(
            {
                "coverage_item_id": coverage_id,
                "requirement_id": requirement_id,
                "coverage_item": f"{field} boundary value {value}",
                "type": "Data Range",
                "rationale": suggestion["rationale"],
            }
        )
        result.setdefault("strategies", []).append(
            {
                "strategy_id": strategy_id,
                "coverage_item_id": coverage_id,
                "technique": "Boundary Value Analysis",
                "method": f"Test {field} at boundary value {value}",
                "rationale": boundary_strategy_rationale(requirement_id, field, suggestion),
            }
        )
        result.setdefault("test_cases", []).append(
            {
                "test_case_id": test_case_id,
                "requirement_id": requirement_id,
                "strategy_id": strategy_id,
                "technique": "Boundary Value Analysis",
                "test_data": build_boundary_test_data(result, requirement_id, field, value),
                "steps": (
                    "1. Prepare the complete input combination shown in test_data. "
                    "2. Submit or execute the target action."
                ),
                "expected_result": expected_result_for_boundary(result, requirement_id, field, value),
                "priority": priority_for_requirement(result, requirement_id),
                "risk_score": risk_for_requirement(result, requirement_id),
                "source": "Automated BVA Supplement",
                "optimization_rank": "",
                "optimization_reason": "",
            }
        )
        result.setdefault("traceability", []).append(
            {
                "requirement_id": requirement_id,
                "coverage_item_id": coverage_id,
                "strategy_id": strategy_id,
                "test_case_id": test_case_id,
            }
        )
        suggestion["status"] = f"Added as {test_case_id}"


def boundary_strategy_rationale(
    requirement_id: str, field: str, suggestion: dict[str, str]
) -> str:
    source_rule = suggestion.get("source_rule", "")
    range_match = re.match(r"range\s+(-?\d+)-(-?\d+)", source_rule)
    if range_match:
        low, high = int(range_match.group(1)), int(range_match.group(2))
        values = [low - 1, low, low + 1, high - 1, high, high + 1]
        value_text = "、".join(str(value) for value in values)
        return (
            f"自动识别 {requirement_id} 中 {display_field_name(field)} 的数值范围 "
            f"[{low},{high}]，按 BVA 标准补充边界点 {value_text} 的测试覆盖。"
        )

    threshold_match = re.match(r"threshold\s+(-?\d+)", source_rule)
    if threshold_match:
        threshold = int(threshold_match.group(1))
        values = [threshold - 1, threshold, threshold + 1]
        value_text = "、".join(str(value) for value in values)
        return (
            f"自动识别 {requirement_id} 中 {display_field_name(field)} 的阈值 "
            f"{threshold}，补充阈值附近 {value_text} 的测试覆盖。"
        )

    return f"根据 {requirement_id} 的输入约束补充 {display_field_name(field)} 的边界测试覆盖。"


def build_boundary_test_data(
    result: dict[str, Any], requirement_id: str, changed_field: str, value: str
) -> str:
    # 中文说明：边界用例必须给出完整输入组合，避免只写 username 或只写 password 造成不可执行用例。
    fields = fields_for_requirement(result, requirement_id, changed_field)
    changed_key = canonical_field_name(changed_field)
    parts: list[str] = []
    for field in fields:
        field_key = canonical_field_name(field)
        if field_key == changed_key:
            field_value = boundary_input_value(field, value)
        else:
            field_value = baseline_input_value(field)
        parts.append(f"{display_field_name(field)} = {field_value}")
    return "; ".join(parts) if parts else f"{display_field_name(changed_field)} = {value}"


def fields_for_requirement(
    result: dict[str, Any], requirement_id: str, changed_field: str
) -> list[str]:
    requirement = next(
        (
            row
            for row in result.get("requirements", [])
            if row.get("requirement_id", "") == requirement_id
        ),
        {},
    )
    fields = split_input_fields(requirement.get("input_fields", ""))
    text = " ".join(requirement.values()).lower()
    if not fields:
        if "username" in text or "用户" in text:
            fields.append("Username")
        if "password" in text or "密码" in text:
            fields.append("Password")
        if "score" in text or "成绩" in text or "分数" in text:
            fields.append("Score")
        if "email" in text:
            fields.append("Email")

    changed_key = canonical_field_name(changed_field)
    if changed_key and all(canonical_field_name(field) != changed_key for field in fields):
        fields.insert(0, changed_field)

    keys = {canonical_field_name(field) for field in fields}
    if {"username", "password"} & keys or "login" in text or "登录" in text:
        if "username" not in keys:
            fields.insert(0, "Username")
        if "password" not in keys:
            fields.append("Password")

    deduped: list[str] = []
    seen: set[str] = set()
    for field in fields:
        key = canonical_field_name(field) or field.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(display_field_name(field))
    return deduped


def split_input_fields(input_fields: str) -> list[str]:
    fields: list[str] = []
    for item in re.split(r"[;,，、/|\n\r]+", input_fields):
        field = item.strip()
        if not field:
            continue
        fields.append(field)
    return fields


def canonical_field_name(field: str) -> str:
    lower = field.strip().lower()
    if "username" in lower or "user name" in lower or "用户名" in lower:
        return "username"
    if "password" in lower or "pwd" in lower or "密码" in lower:
        return "password"
    if "score" in lower or "grade" in lower or "成绩" in lower or "分数" in lower:
        return "score"
    if "email" in lower or "邮箱" in lower:
        return "email"
    return lower


def display_field_name(field: str) -> str:
    key = canonical_field_name(field)
    if key == "username":
        return "Username"
    if key == "password":
        return "Password"
    if key == "score":
        return "Score"
    if key == "email":
        return "Email"
    return field.strip() or "Input"


def baseline_input_value(field: str) -> str:
    key = canonical_field_name(field)
    if key == "username":
        return "'valid_user'"
    if key == "password":
        return "'ValidPass1'"
    if key == "score":
        return "75"
    if key == "email":
        return "'user@example.com'"
    return "'valid'"


def boundary_input_value(field: str, value: str) -> str:
    key = canonical_field_name(field)
    if key in {"username", "password"}:
        length = safe_int(value)
        if length < 0:
            return f"'<invalid length {value}>'"
        return f"'{sample_string_for_length(key, length)}' (length {length})"
    return value


def sample_string_for_length(field_key: str, length: int) -> str:
    if length <= 0:
        return ""
    seed = "Valid1XyZ0" if field_key == "password" else "validuserx"
    return (seed * ((length // len(seed)) + 1))[:length]


def repair_missing_design_links(result: dict[str, Any]) -> None:
    coverage_ids = {row.get("coverage_item_id", "") for row in result.get("coverage_items", [])}
    coverage_ids.update(row.get("coverage_item_id", "") for row in result.get("traceability", []))
    strategy_ids = {row.get("strategy_id", "") for row in result.get("strategies", [])}
    strategy_ids.update(row.get("strategy_id", "") for row in result.get("test_cases", []))
    strategy_ids.update(row.get("strategy_id", "") for row in result.get("traceability", []))
    test_case_ids = {row.get("test_case_id", "") for row in result.get("test_cases", [])}

    strategies_by_coverage: dict[str, list[dict[str, str]]] = {}
    for strategy in result.get("strategies", []):
        strategies_by_coverage.setdefault(strategy.get("coverage_item_id", ""), []).append(strategy)

    traced_coverage_ids = {
        row.get("coverage_item_id", "")
        for row in result.get("traceability", [])
        if row.get("coverage_item_id", "") and row.get("test_case_id", "")
    }
    for coverage_item in result.get("coverage_items", []):
        coverage_id = coverage_item.get("coverage_item_id", "")
        if not coverage_id or strategies_by_coverage.get(coverage_id) or coverage_id in traced_coverage_ids:
            continue
        strategy_id = next_id("ST", strategy_ids)
        strategy_ids.add(strategy_id)
        technique = (
            "Boundary Value Analysis"
            if coverage_item.get("type", "") == "Data Range"
            else "Equivalence Partitioning"
        )
        strategy = {
            "strategy_id": strategy_id,
            "coverage_item_id": coverage_id,
            "technique": technique,
            "method": f"Complete strategy coverage for {coverage_id}",
            "rationale": f"补全覆盖项 {coverage_id} 的测试策略，确保该覆盖点可以追溯到具体测试用例。",
        }
        result.setdefault("strategies", []).append(strategy)
        strategies_by_coverage.setdefault(coverage_id, []).append(strategy)

    test_cases_by_strategy: dict[str, list[dict[str, str]]] = {}
    for test_case in result.get("test_cases", []):
        test_cases_by_strategy.setdefault(test_case.get("strategy_id", ""), []).append(test_case)

    coverage_by_id = {
        row.get("coverage_item_id", ""): row for row in result.get("coverage_items", [])
    }
    for strategy in result.get("strategies", []):
        strategy_id = strategy.get("strategy_id", "")
        if not strategy_id or test_cases_by_strategy.get(strategy_id):
            continue
        coverage_item = coverage_by_id.get(strategy.get("coverage_item_id", ""), {})
        if coverage_item.get("coverage_item_id", "") in traced_coverage_ids:
            continue
        requirement_id = coverage_item.get("requirement_id", "")
        test_case_id = next_id("TC", test_case_ids)
        test_case_ids.add(test_case_id)
        repaired_case = repair_test_case_content(result, requirement_id, coverage_item)
        result.setdefault("test_cases", []).append(
            {
                "test_case_id": test_case_id,
                "requirement_id": requirement_id,
                "strategy_id": strategy_id,
                "technique": strategy.get("technique", "Equivalence Partitioning"),
                "test_data": repaired_case["test_data"],
                "steps": repaired_case["steps"],
                "expected_result": repaired_case["expected_result"],
                "priority": priority_for_requirement(result, requirement_id),
                "risk_score": risk_for_requirement(result, requirement_id),
                "source": "Traceability Completion",
                "optimization_rank": "",
                "optimization_reason": "",
            }
        )

    existing_trace_pairs = {
        (row.get("strategy_id", ""), row.get("test_case_id", ""))
        for row in result.get("traceability", [])
    }
    coverage_id_by_strategy = {
        row.get("strategy_id", ""): row.get("coverage_item_id", "")
        for row in result.get("strategies", [])
    }
    requirement_id_by_coverage = {
        row.get("coverage_item_id", ""): row.get("requirement_id", "")
        for row in result.get("coverage_items", [])
    }
    for test_case in result.get("test_cases", []):
        strategy_id = test_case.get("strategy_id", "")
        test_case_id = test_case.get("test_case_id", "")
        if not strategy_id or not test_case_id or (strategy_id, test_case_id) in existing_trace_pairs:
            continue
        coverage_id = coverage_id_by_strategy.get(strategy_id, "")
        result.setdefault("traceability", []).append(
            {
                "requirement_id": test_case.get("requirement_id", "")
                or requirement_id_by_coverage.get(coverage_id, ""),
                "coverage_item_id": coverage_id,
                "strategy_id": strategy_id,
                "test_case_id": test_case_id,
            }
        )
        existing_trace_pairs.add((strategy_id, test_case_id))


def repair_test_case_content(
    result: dict[str, Any], requirement_id: str, coverage_item: dict[str, str]
) -> dict[str, str]:
    # 中文说明：补齐追溯链时也要生成可执行用例，不能留下泛化占位文本。
    coverage_text = coverage_item.get("coverage_item", "").lower()
    if "password" in coverage_text and ("missing digit" in coverage_text or "数字" in coverage_text):
        return {
            "test_data": "Username: 'validuser', Password: 'NoDigitsHere'",
            "steps": "1. Enter valid username. 2. Enter password without digits. 3. Click Login.",
            "expected_result": "System rejects with error: 'Password must contain at least one digit.'",
        }
    if "password" in coverage_text and (
        "missing uppercase" in coverage_text or "uppercase" in coverage_text or "大写" in coverage_text
    ):
        return {
            "test_data": "Username: 'validuser', Password: 'lowercase1'",
            "steps": "1. Enter valid username. 2. Enter password without uppercase letters. 3. Click Login.",
            "expected_result": "System rejects with error: 'Password must contain at least one uppercase letter.'",
        }
    if "username" in coverage_text and ("length" in coverage_text or "长度" in coverage_text):
        return {
            "test_data": "Username: 'validuser', Password: 'Valid1Xy'",
            "steps": "1. Enter valid username. 2. Enter valid password. 3. Click Login.",
            "expected_result": "Login proceeds normally when other fields are valid.",
        }

    expected_action = expected_action_for_requirement(result, requirement_id)
    fields = fields_for_requirement(result, requirement_id, "input")
    test_data = "; ".join(f"{field} = {baseline_input_value(field)}" for field in fields)
    return {
        "test_data": test_data or f"Representative input for {coverage_item.get('coverage_item', requirement_id)}",
        "steps": "1. Prepare the specified input data. 2. Execute the target behavior. 3. Observe the result.",
        "expected_result": expected_action,
    }


def expected_result_for_boundary(
    result: dict[str, Any], requirement_id: str, field: str, value: str
) -> str:
    requirement = next(
        (
            row
            for row in result.get("requirements", [])
            if row.get("requirement_id", "") == requirement_id
        ),
        {},
    )
    text = " ".join(requirement.values()).lower()
    numeric_value = int(value)

    range_match = re.search(r"(?<!\d)(-?\d+)\s*(?:-|~|–|至|到|to)\s*(-?\d+)(?!\d)", text, flags=re.IGNORECASE)
    if range_match:
        low, high = int(range_match.group(1)), int(range_match.group(2))
        if low > high:
            low, high = high, low
        if numeric_value < low or numeric_value > high:
            return invalid_boundary_message(field, value, low, high)
        return valid_boundary_message(field, value, low, high)

    excellent = labeled_threshold(text, ["excellent", "优秀"])
    passed = labeled_threshold(text, ["pass", "及格"])
    if excellent is not None and numeric_value >= excellent:
        return "Grade displayed as 'Excellent' / 优秀。"
    if passed is not None and numeric_value >= passed:
        return "Grade displayed as 'Pass' / 及格。"
    if passed is not None:
        return "Grade displayed as 'Fail' / 不及格。"
    return f"{display_field_name(field)}={value} is evaluated according to {requirement_id}; expected result should match the linked requirement action."


def valid_boundary_message(field: str, value: str, low: int, high: int) -> str:
    field_name = display_field_name(field)
    if canonical_field_name(field) in {"username", "password"}:
        return (
            f"{field_name} length {value} is accepted because it is within {low}-{high}; "
            "login proceeds normally when other fields are valid."
        )
    return f"{field_name}={value} is accepted because it is within the valid range {low}-{high}."


def invalid_boundary_message(field: str, value: str, low: int, high: int) -> str:
    field_name = display_field_name(field)
    if canonical_field_name(field) in {"username", "password"}:
        return f"System rejects with error: '{field_name} must be {low}-{high} characters.'"
    return f"System rejects {field_name}={value} because it is outside the valid range {low}-{high}."


def expected_action_for_requirement(result: dict[str, Any], requirement_id: str) -> str:
    requirement = next(
        (
            row
            for row in result.get("requirements", [])
            if row.get("requirement_id", "") == requirement_id
        ),
        {},
    )
    return requirement.get("expected_actions", "") or f"Expected action for {requirement_id} is observed."


def labeled_threshold(text: str, labels: list[str]) -> int | None:
    for label in labels:
        match = re.search(rf"{re.escape(label)}[^\d-]{{0,12}}(-?\d+)", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def value_present(text: str, value: str) -> bool:
    return re.search(rf"(?<![-\d.]){re.escape(value)}(?![\d.])", text) is not None


def priority_for_requirement(result: dict[str, Any], requirement_id: str) -> str:
    risk = risk_row(result, requirement_id)
    return risk.get("priority", "Medium")


def risk_for_requirement(result: dict[str, Any], requirement_id: str) -> str:
    risk = risk_row(result, requirement_id)
    return risk.get("risk_score", "50")


def risk_row(result: dict[str, Any], requirement_id: str) -> dict[str, str]:
    return next(
        (
            row
            for row in result.get("risks", [])
            if row.get("requirement_id", "") == requirement_id
        ),
        {},
    )


def optimize_test_suite(result: dict[str, Any]) -> None:
    trace_count: dict[str, int] = {}
    for row in result.get("traceability", []):
        test_case_id = row.get("test_case_id", "")
        if test_case_id:
            trace_count[test_case_id] = trace_count.get(test_case_id, 0) + 1

    def score(test_case: dict[str, str]) -> tuple[int, int, int, int]:
        risk_score = safe_int(test_case.get("risk_score", "0"))
        priority_weight = {"High": 30, "Medium": 15, "Low": 0}.get(
            test_case.get("priority", ""), 0
        )
        boundary_bonus = 10 if "boundary" in test_case.get("technique", "").lower() else 0
        coverage_bonus = trace_count.get(test_case.get("test_case_id", ""), 0)
        return (risk_score + priority_weight + boundary_bonus + coverage_bonus, risk_score, priority_weight, coverage_bonus)

    ranked_cases = sorted(result.get("test_cases", []), key=score, reverse=True)
    for rank, test_case in enumerate(ranked_cases, start=1):
        reason_parts = [
            f"risk={test_case.get('risk_score', '')}",
            f"priority={test_case.get('priority', '')}",
        ]
        if "boundary" in test_case.get("technique", "").lower():
            reason_parts.append("boundary-value bonus")
        if trace_count.get(test_case.get("test_case_id", ""), 0):
            reason_parts.append(f"covers {trace_count[test_case.get('test_case_id', '')]} trace item(s)")
        test_case["optimization_rank"] = str(rank)
        test_case["optimization_reason"] = "; ".join(reason_parts)
        if not test_case.get("source", ""):
            test_case["source"] = "LLM"
    # 中文说明：推荐执行顺序写入 optimization_rank，但表格展示保持 TC 编号升序，避免审查时看起来乱序。
    result["test_cases"] = sorted(result.get("test_cases", []), key=test_case_sort_key)
    result["optimization_summary"] = (
        "Test suite ranked by risk score, priority, boundary-value coverage, and traceability coverage."
    )


def test_case_sort_key(test_case: dict[str, str]) -> tuple[int, int, str]:
    test_case_id = test_case.get("test_case_id", "")
    match = re.match(r"^TC-(\d+)$", test_case_id)
    if match:
        return (0, int(match.group(1)), test_case_id)
    return (1, 0, test_case_id)


def build_state_model(result: dict[str, Any]) -> None:
    if result.get("state_model") and result.get("state_sequences"):
        return

    transitions: list[dict[str, str]] = []
    for index, requirement in enumerate(result.get("requirements", []), start=1):
        requirement_id = requirement.get("requirement_id", "")
        transitions.append(
            {
                "transition_id": f"TR-{index:03d}",
                "requirement_id": requirement_id,
                "state_name": "Ready",
                "event": f"Evaluate {requirement_id}",
                "condition": requirement.get("conditions", ""),
                "next_state": infer_next_state(requirement),
                "expected_action": requirement.get("expected_actions", ""),
            }
        )

    result["state_model"] = transitions
    if transitions:
        result["state_sequences"] = [
            {
                "sequence_id": "SEQ-001",
                "coverage_criterion": "All Transitions",
                "sequence": " -> ".join(row["transition_id"] for row in transitions),
                "covered_transitions": ", ".join(row["transition_id"] for row in transitions),
                "rationale": "根据结构化需求生成轻量状态/转移覆盖序列。",
            }
        ]


def infer_next_state(requirement: dict[str, str]) -> str:
    text = " ".join(requirement.values()).lower()
    if "lock" in text or "锁" in text:
        return "Locked"
    if "error" in text or "invalid" in text or "错误" in text or "失败" in text:
        return "Error"
    if "success" in text or "valid" in text or "通过" in text or "成功" in text:
        return "Success"
    return "Completed"


def next_id(prefix: str, existing_ids: set[str]) -> str:
    max_number = 0
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    for item_id in existing_ids:
        match = pattern.match(item_id)
        if match:
            max_number = max(max_number, int(match.group(1)))
    return f"{prefix}-{max_number + 1:03d}"


def safe_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
