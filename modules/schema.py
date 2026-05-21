from __future__ import annotations

import copy
from typing import Any


TABLE_COLUMNS = {
    "requirements": [
        "requirement_id",
        "raw_text",
        "input_fields",
        "data_ranges",
        "conditions",
        "expected_actions",
    ],
    "risks": ["requirement_id", "risk_score", "priority", "reason"],
    "coverage_items": [
        "coverage_item_id",
        "requirement_id",
        "coverage_item",
        "type",
        "rationale",
    ],
    "strategies": [
        "strategy_id",
        "coverage_item_id",
        "technique",
        "method",
        "rationale",
    ],
    "test_cases": [
        "test_case_id",
        "requirement_id",
        "strategy_id",
        "technique",
        "test_data",
        "steps",
        "expected_result",
        "priority",
        "risk_score",
    ],
    "traceability": [
        "requirement_id",
        "coverage_item_id",
        "strategy_id",
        "test_case_id",
    ],
}


MODEL_COLUMNS = [
    "model_type",
    "model_description",
    "coverage_criterion",
    "optimal_sequence",
    "rationale",
]


RESULT_KEYS = [
    "project",
    "requirements",
    "risks",
    "coverage_items",
    "strategies",
    "test_cases",
    "traceability",
    "white_box_model",
    "optimization_summary",
    "result_analysis",
]


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(_stringify(item) for item in value)
    if isinstance(value, dict):
        return "; ".join(f"{key}: {_stringify(val)}" for key, val in value.items())
    return str(value)


def normalize_rows(rows: Any, columns: list[str]) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        rows = []
    normalized: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized.append({column: _stringify(row.get(column, "")) for column in columns})
    return normalized


def normalize_result(raw: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(raw)
    if not isinstance(result.get("project"), dict):
        result["project"] = {}
    for key, columns in TABLE_COLUMNS.items():
        result[key] = normalize_rows(result.get(key), columns)
    result["white_box_model"] = normalize_rows(
        result.get("white_box_model"), MODEL_COLUMNS
    )
    result["optimization_summary"] = _stringify(result.get("optimization_summary", ""))
    result["result_analysis"] = _stringify(result.get("result_analysis", ""))
    return result


def empty_result() -> dict[str, Any]:
    return {
        "project": {},
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
