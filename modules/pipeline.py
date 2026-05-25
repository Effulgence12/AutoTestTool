from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .llm_client import LLMResponseError, call_qwen_json
from .schema import normalize_result


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


def read_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def generate_design(
    target_app: str,
    target_module: str,
    requirements_text: str,
    expected_requirement_ids: list[str] | None = None,
) -> tuple[dict[str, Any], float, str]:
    system_prompt = read_prompt("system_prompt.txt")
    user_template = read_prompt("full_design_prompt.txt")
    user_prompt = user_template.format(
        target_app=target_app.strip() or "Unnamed target application",
        target_module=target_module.strip() or "Main module",
        requirements_text=requirements_text.strip(),
    )

    start = time.perf_counter()
    raw = call_qwen_json(system_prompt, user_prompt)
    elapsed = time.perf_counter() - start
    result = normalize_result(raw)
    validate_design_result(result, expected_requirement_ids)
    return result, elapsed, user_prompt


def regenerate_requirement(
    target_app: str,
    target_module: str,
    requirement_row: dict[str, Any],
) -> tuple[dict[str, Any], float, str]:
    system_prompt = read_prompt("system_prompt.txt")
    user_template = read_prompt("regenerate_prompt.txt")
    user_prompt = user_template.format(
        target_app=target_app.strip() or "Unnamed target application",
        target_module=target_module.strip() or "Main module",
        requirement_json=json.dumps(requirement_row, ensure_ascii=False),
    )
    start = time.perf_counter()
    raw = call_qwen_json(system_prompt, user_prompt)
    elapsed = time.perf_counter() - start
    result = normalize_result(raw)
    validate_design_result(result)
    return result, elapsed, user_prompt


def validate_design_result(
    result: dict[str, Any],
    expected_requirement_ids: list[str] | None = None,
) -> None:
    if expected_requirement_ids:
        generated_requirement_ids = [
            row.get("requirement_id", "")
            for row in result.get("requirements", [])
            if row.get("requirement_id", "")
        ]
        generated_requirement_id_set = set(generated_requirement_ids)
        missing_requirement_ids = [
            requirement_id
            for requirement_id in expected_requirement_ids
            if requirement_id not in generated_requirement_id_set
        ]
        duplicate_requirement_ids = sorted(
            {
                requirement_id
                for requirement_id in generated_requirement_ids
                if generated_requirement_ids.count(requirement_id) > 1
            }
        )
        if missing_requirement_ids:
            raise LLMResponseError(
                "Qwen response is incomplete: missing CSV requirement rows "
                + ", ".join(missing_requirement_ids)
            )
        if duplicate_requirement_ids:
            raise LLMResponseError(
                "Qwen response duplicated CSV requirement rows "
                + ", ".join(duplicate_requirement_ids)
            )

    requirement_ids = {
        row.get("requirement_id", "")
        for row in result.get("requirements", [])
        if row.get("requirement_id", "")
    }
    risk_ids = {
        row.get("requirement_id", "")
        for row in result.get("risks", [])
        if row.get("requirement_id", "")
    }
    missing_risks = sorted(requirement_ids - risk_ids)
    if missing_risks:
        raise LLMResponseError(
            "Qwen response is incomplete: missing risk rows for "
            + ", ".join(missing_risks)
        )

    techniques = " | ".join(
        row.get("technique", "") for row in result.get("test_cases", [])
    ).lower()
    required_markers = [
        "equivalence",
        "boundary",
        "decision",
    ]
    missing_techniques = [
        marker for marker in required_markers if marker not in techniques
    ]
    if missing_techniques:
        raise LLMResponseError(
            "Qwen response is incomplete: missing required black-box techniques "
            + ", ".join(missing_techniques)
        )


def build_improvement_evidence(
    original: dict[str, Any] | None,
    current: dict[str, Any],
    notes: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    if not original:
        return []

    notes = notes or {}
    evidence: list[dict[str, str]] = []
    tracked = [
        ("coverage_items", "coverage_item_id", "Coverage Item"),
        ("strategies", "strategy_id", "Coverage Strategy"),
        ("test_cases", "test_case_id", "Test Case"),
        ("traceability", "test_case_id", "Traceability"),
    ]
    for table_key, id_key, label in tracked:
        before_rows = original.get(table_key, [])
        after_rows = current.get(table_key, [])
        before = {row.get(id_key, ""): row for row in before_rows if row.get(id_key, "")}
        after = {row.get(id_key, ""): row for row in after_rows if row.get(id_key, "")}

        for row_id, row in after.items():
            if row_id not in before:
                evidence_key = f"{table_key}:{row_id}:Added"
                note = notes.get(evidence_key, {})
                reason = note.get("reason", "")
                gap_identified = note.get("gap_identified", "")
                evidence.append(
                    {
                        "evidence_key": evidence_key,
                        "item_type": label,
                        "item_id": row_id,
                        "change_type": "Added",
                        "field_changed": "",
                        "old_value": "",
                        "new_value": summarize_row(row),
                        "reason": reason,
                        "gap_identified": gap_identified,
                        "evidence": build_evidence_text(
                            "added", label, row_id, reason, gap_identified
                        ),
                    }
                )
            elif row != before[row_id]:
                for field, old_value in before[row_id].items():
                    new_value = row.get(field, "")
                    if new_value == old_value:
                        continue
                    evidence_key = f"{table_key}:{row_id}:Modified:{field}"
                    note = notes.get(evidence_key, {})
                    reason = note.get("reason", "")
                    gap_identified = note.get("gap_identified", "")
                    evidence.append(
                        {
                            "evidence_key": evidence_key,
                            "item_type": label,
                            "item_id": row_id,
                            "change_type": "Modified",
                            "field_changed": field,
                            "old_value": old_value,
                            "new_value": new_value,
                            "reason": reason,
                            "gap_identified": gap_identified,
                            "evidence": build_evidence_text(
                                "modified", label, row_id, reason, gap_identified, field
                            ),
                        }
                    )

        for row_id in before:
            if row_id not in after:
                evidence_key = f"{table_key}:{row_id}:Removed"
                note = notes.get(evidence_key, {})
                reason = note.get("reason", "")
                gap_identified = note.get("gap_identified", "")
                evidence.append(
                    {
                        "evidence_key": evidence_key,
                        "item_type": label,
                        "item_id": row_id,
                        "change_type": "Removed",
                        "field_changed": "",
                        "old_value": summarize_row(before[row_id]),
                        "new_value": "",
                        "reason": reason,
                        "gap_identified": gap_identified,
                        "evidence": build_evidence_text(
                            "removed", label, row_id, reason, gap_identified
                        ),
                    }
                )

    return evidence


def summarize_row(row: dict[str, str]) -> str:
    parts = [f"{key}={value}" for key, value in row.items() if value]
    return "; ".join(parts)


def build_evidence_text(
    action: str,
    label: str,
    row_id: str,
    reason: str,
    gap_identified: str,
    field: str = "",
) -> str:
    if action == "added":
        base = f"Designer added {row_id} after reviewing {label.lower()} coverage."
    elif action == "modified":
        base = f"Designer modified {field} of {row_id} during interactive review."
    else:
        base = f"Designer removed {row_id} during interactive review."

    details = []
    if gap_identified:
        details.append(f"Gap: {gap_identified}")
    if reason:
        details.append(f"Reason: {reason}")
    if details:
        return base + " " + " ".join(details)
    return base
