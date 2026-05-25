from __future__ import annotations

import copy
import io
from typing import Any

import pandas as pd
import streamlit as st

from modules.exporter import (
    result_to_csv_zip_bytes,
    result_to_excel_bytes,
    result_to_json_bytes,
)
from modules.llm_client import LLMConfigurationError, LLMResponseError, model_name, smoke_test
from modules.pipeline import (
    build_improvement_evidence,
    generate_design,
    regenerate_requirement,
)
from modules.schema import MODEL_COLUMNS, TABLE_COLUMNS, empty_result, normalize_result


st.set_page_config(page_title="AutoTestDesign Tool", layout="wide")


def init_state() -> None:
    defaults = {
        "result": empty_result(),
        "original_result": None,
        "last_prompt": "",
        "last_elapsed": None,
        "last_model": "",
        "last_error": "",
        "smoke_result": "",
        "optimization_summary_text": "",
        "result_analysis_text": "",
        "evidence_notes": {},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def csv_requirement_ids(df: pd.DataFrame) -> list[str]:
    normalized_columns = {str(column).strip().lower(): column for column in df.columns}
    id_column = None
    for candidate in ["req_id", "requirement_id", "id"]:
        if candidate in normalized_columns:
            id_column = normalized_columns[candidate]
            break
    if id_column is None:
        return []
    return [
        str(value).strip()
        for value in df[id_column].fillna("").tolist()
        if str(value).strip()
    ]


def csv_prompt_block(file_name: str, df: pd.DataFrame, requirement_ids: list[str]) -> str:
    csv_text = df.to_csv(index=False)
    if not requirement_ids:
        return csv_text
    return (
        f"CSV file: {file_name}\n"
        f"CSV requirement row count: {len(df)}\n"
        "Required requirement_id values, one per CSV data row: "
        + ", ".join(requirement_ids)
        + "\n"
        "CSV parsing rule: each listed requirement_id must appear exactly once in the "
        "requirements array. Preserve these IDs exactly; do not merge, split, omit, "
        "or renumber CSV rows.\n"
        + csv_text
    )


def uploaded_text(files: list[Any]) -> tuple[str, list[str]]:
    parts: list[str] = []
    expected_requirement_ids: list[str] = []
    for file in files:
        name = file.name.lower()
        data = file.getvalue()
        if name.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(data))
            requirement_ids = csv_requirement_ids(df)
            expected_requirement_ids.extend(requirement_ids)
            parts.append(csv_prompt_block(file.name, df, requirement_ids))
        else:
            parts.append(data.decode("utf-8", errors="replace"))
    return "\n\n".join(parts), expected_requirement_ids


def dataframe_for(result: dict[str, Any], key: str, columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(result.get(key, []), columns=columns).fillna("")


def apply_table_edit(result: dict[str, Any], key: str, edited: pd.DataFrame) -> None:
    result[key] = edited.fillna("").astype(str).to_dict(orient="records")


def current_result_with_evidence() -> dict[str, Any]:
    current = normalize_result(copy.deepcopy(st.session_state.result))
    current["improvement_evidence"] = build_improvement_evidence(
        st.session_state.original_result, current, st.session_state.evidence_notes
    )
    return current


def sync_evidence_notes(edited: pd.DataFrame) -> None:
    notes: dict[str, dict[str, str]] = copy.deepcopy(st.session_state.evidence_notes)
    if edited.empty or "evidence_key" not in edited.columns:
        return
    for row in edited.fillna("").astype(str).to_dict(orient="records"):
        evidence_key = row.get("evidence_key", "")
        if not evidence_key:
            continue
        notes[evidence_key] = {
            "reason": row.get("reason", ""),
            "gap_identified": row.get("gap_identified", ""),
        }
    st.session_state.evidence_notes = notes


def review_validation_issues(result: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    required_test_case_fields = [
        "test_case_id",
        "requirement_id",
        "strategy_id",
        "technique",
        "test_data",
        "steps",
        "expected_result",
        "priority",
        "risk_score",
    ]
    test_cases = result.get("test_cases", [])
    traceability = result.get("traceability", [])
    tc_ids = {row.get("test_case_id", "") for row in test_cases if row.get("test_case_id", "")}
    traced_tc_ids = {
        row.get("test_case_id", "") for row in traceability if row.get("test_case_id", "")
    }

    for index, row in enumerate(test_cases, start=1):
        row_id = row.get("test_case_id", "") or f"第 {index} 行"
        missing_fields = [
            field for field in required_test_case_fields if not row.get(field, "").strip()
        ]
        if missing_fields:
            issues.append(f"{row_id} 存在空字段：{', '.join(missing_fields)}。")

    for tc_id in sorted(tc_ids - traced_tc_ids):
        issues.append(f"{tc_id} 没有对应的 traceability 追溯记录。")

    for tc_id in sorted(traced_tc_ids - tc_ids):
        issues.append(f"traceability 中的 {tc_id} 不存在于 test_cases 表。")

    return issues


def render_editors() -> None:
    result = st.session_state.result
    st.subheader("交互式审查")
    st.caption("这些表格都可编辑。人工新增、删除或修改覆盖项、策略、用例和追溯关系后，会进入改进证据。")

    tabs = st.tabs(
        [
            "结构化需求",
            "风险分析",
            "覆盖项",
            "策略方法",
            "测试用例",
            "追溯矩阵",
            "白盒模型",
        ]
    )
    table_items = list(TABLE_COLUMNS.items())
    for tab, (key, columns) in zip(tabs[:6], table_items):
        with tab:
            edited = st.data_editor(
                dataframe_for(result, key, columns),
                num_rows="dynamic",
                width='stretch',
                key=f"editor_{key}",
            )
            apply_table_edit(result, key, edited)

    with tabs[6]:
        edited_model = st.data_editor(
            pd.DataFrame(result.get("white_box_model", []), columns=MODEL_COLUMNS).fillna(""),
            num_rows="dynamic",
            width='stretch',
            key="editor_white_box_model",
        )
        result["white_box_model"] = edited_model.fillna("").astype(str).to_dict(
            orient="records"
        )


def render_generation_controls(
    target_app: str,
    target_module: str,
    requirements: str,
    expected_requirement_ids: list[str] | None = None,
) -> None:
    st.subheader("生成区")
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        generate_clicked = st.button("生成测试设计", type="primary", width='stretch')
    with col2:
        smoke_clicked = st.button("验证 Qwen 配置", width='stretch')
    with col3:
        try:
            st.info(f"当前模型：{model_name()}")
        except Exception as exc:
            st.warning(f"模型配置未就绪：{exc}")

    if smoke_clicked:
        try:
            response = smoke_test()
            st.session_state.smoke_result = f"Qwen 配置验证成功：{response}"
            st.session_state.last_error = ""
        except (LLMConfigurationError, LLMResponseError) as exc:
            st.session_state.smoke_result = ""
            st.session_state.last_error = str(exc)

    if st.session_state.smoke_result:
        st.success(st.session_state.smoke_result)

    if generate_clicked:
        if not requirements.strip():
            st.error("请先输入或上传目标应用需求。")
            return
        try:
            result, elapsed, prompt = generate_design(
                target_app,
                target_module,
                requirements,
                expected_requirement_ids=expected_requirement_ids,
            )
            st.session_state.result = result
            st.session_state.original_result = copy.deepcopy(result)
            st.session_state.last_prompt = prompt
            st.session_state.last_elapsed = elapsed
            st.session_state.last_model = model_name()
            st.session_state.last_error = ""
            st.session_state.optimization_summary_text = result.get(
                "optimization_summary", ""
            )
            st.session_state.result_analysis_text = result.get("result_analysis", "")
        except (LLMConfigurationError, LLMResponseError) as exc:
            st.session_state.last_error = str(exc)

    if st.session_state.last_elapsed is not None:
        st.success(
            f"生成成功。模型：{st.session_state.last_model}；耗时：{st.session_state.last_elapsed:.2f} 秒。"
        )
    if st.session_state.last_error:
        st.error(st.session_state.last_error)


def render_regeneration(target_app: str, target_module: str) -> None:
    requirements = st.session_state.result.get("requirements", [])
    if not requirements:
        return

    st.subheader("单条需求重新生成")
    req_ids = [row.get("requirement_id", "") for row in requirements]
    selected = st.selectbox("选择要重新生成的需求", req_ids)
    if st.button("调用 Qwen 重新生成选中需求内容"):
        row = next((item for item in requirements if item.get("requirement_id") == selected), None)
        if row:
            try:
                partial, elapsed, prompt = regenerate_requirement(
                    target_app, target_module, row
                )
                st.session_state.last_prompt = prompt
                st.session_state.last_elapsed = elapsed
                st.session_state.last_model = model_name()
                st.session_state.last_error = ""
                st.session_state.result = merge_partial_result(st.session_state.result, partial)
                st.session_state.optimization_summary_text = st.session_state.result.get(
                    "optimization_summary", ""
                )
                st.session_state.result_analysis_text = st.session_state.result.get(
                    "result_analysis", ""
                )
                st.success(f"重新生成完成，耗时 {elapsed:.2f} 秒。")
            except (LLMConfigurationError, LLMResponseError) as exc:
                st.session_state.last_error = str(exc)
                st.error(str(exc))


def merge_partial_result(base: dict[str, Any], partial: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    partial_req_ids = {
        row.get("requirement_id", "") for row in partial.get("requirements", [])
    }
    partial_ci_ids = {
        row.get("coverage_item_id", "") for row in partial.get("coverage_items", [])
    }
    partial_strategy_ids = {
        row.get("strategy_id", "") for row in partial.get("strategies", [])
    }
    partial_tc_ids = {row.get("test_case_id", "") for row in partial.get("test_cases", [])}

    merged["requirements"] = [
        row for row in merged.get("requirements", []) if row.get("requirement_id", "") not in partial_req_ids
    ] + partial.get("requirements", [])
    merged["risks"] = [
        row for row in merged.get("risks", []) if row.get("requirement_id", "") not in partial_req_ids
    ] + partial.get("risks", [])
    merged["coverage_items"] = [
        row for row in merged.get("coverage_items", []) if row.get("coverage_item_id", "") not in partial_ci_ids
    ] + partial.get("coverage_items", [])
    merged["strategies"] = [
        row for row in merged.get("strategies", []) if row.get("strategy_id", "") not in partial_strategy_ids
    ] + partial.get("strategies", [])
    merged["test_cases"] = [
        row for row in merged.get("test_cases", []) if row.get("test_case_id", "") not in partial_tc_ids
    ] + partial.get("test_cases", [])
    merged["traceability"] = [
        row
        for row in merged.get("traceability", [])
        if row.get("requirement_id", "") not in partial_req_ids
    ] + partial.get("traceability", [])
    merged["white_box_model"] = partial.get("white_box_model", merged.get("white_box_model", []))
    merged["optimization_summary"] = partial.get(
        "optimization_summary", merged.get("optimization_summary", "")
    )
    merged["result_analysis"] = partial.get(
        "result_analysis", merged.get("result_analysis", "")
    )
    return normalize_result(merged)


def render_exports(current: dict[str, Any], validation_issues: list[str]) -> None:
    st.subheader("导出区")
    has_blocking_issues = bool(validation_issues)
    if has_blocking_issues:
        st.error("导出前请先修复交互审查问题，避免提交空用例或断裂追溯。")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button(
            "下载 JSON",
            result_to_json_bytes(current),
            file_name="autotestdesign_artifact.json",
            mime="application/json",
            width='stretch',
            disabled=has_blocking_issues,
        )
    with col2:
        st.download_button(
            "下载 CSV ZIP",
            result_to_csv_zip_bytes(current),
            file_name="autotestdesign_csv.zip",
            mime="application/zip",
            width='stretch',
            disabled=has_blocking_issues,
        )
    with col3:
        st.download_button(
            "下载 Excel",
            result_to_excel_bytes(current),
            file_name="autotestdesign_artifact.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width='stretch',
            disabled=has_blocking_issues,
        )

    with st.expander("Prompt 设计记录"):
        st.text_area("最近一次发送给 Qwen 的 Prompt", st.session_state.last_prompt, height=260)


def main() -> None:
    init_state()

    st.title("AutoTestDesign Tool")
    st.write("面向课程 Assignment 2 的 AI 驱动测试设计工具：真实调用 Qwen，支持人工审查、修改和导出。")

    st.subheader("输入区")
    target_app = st.text_input("目标应用名称", value="Login Module Demo")
    target_module = st.text_input("主要模块或特性", value="User Login")
    typed_requirements = st.text_area(
        "需求文本",
        height=180,
        placeholder="示例：用户登录时，用户名长度必须为 6-20 个字符，密码不能为空。连续 5 次失败后账号锁定 10 分钟。",
    )
    files = st.file_uploader(
        "上传 TXT 或 CSV 需求文件",
        type=["txt", "csv"],
        accept_multiple_files=True,
    )
    file_text, expected_requirement_ids = uploaded_text(files) if files else ("", [])
    requirements = "\n\n".join(part for part in [typed_requirements, file_text] if part)

    render_generation_controls(
        target_app,
        target_module,
        requirements,
        expected_requirement_ids,
    )
    render_regeneration(target_app, target_module)

    render_editors()

    st.subheader("改进证据区")
    current = current_result_with_evidence()
    evidence = current.get("improvement_evidence", [])
    if evidence:
        st.caption("检测到新增、修改或删除后，请填写 reason / gap_identified，作为人工审查证据。")
        evidence_df = pd.DataFrame(evidence)
        edited_evidence = st.data_editor(
            evidence_df,
            width='stretch',
            num_rows="fixed",
            disabled=[
                "evidence_key",
                "item_type",
                "item_id",
                "change_type",
                "field_changed",
                "old_value",
                "new_value",
                "evidence",
            ],
            key="evidence_editor",
        )
        sync_evidence_notes(edited_evidence)
        current = current_result_with_evidence()
    else:
        st.info("还没有检测到人工新增、修改或删除。")

    validation_issues = review_validation_issues(current)
    st.subheader("导出前质量检查")
    if validation_issues:
        for issue in validation_issues:
            st.warning(issue)
    else:
        st.success("测试用例必填字段完整，traceability 与 test_cases 一致。")

    st.subheader("分析摘要")
    st.text_area(
        "优化摘要",
        height=100,
        key="optimization_summary_text",
    )
    st.session_state.result["optimization_summary"] = (
        st.session_state.optimization_summary_text
    )
    st.text_area(
        "结果分析",
        height=120,
        key="result_analysis_text",
    )
    st.session_state.result["result_analysis"] = st.session_state.result_analysis_text

    current = current_result_with_evidence()
    validation_issues = review_validation_issues(current)
    render_exports(current, validation_issues)


if __name__ == "__main__":
    main()
