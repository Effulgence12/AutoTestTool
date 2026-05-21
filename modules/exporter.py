from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pandas as pd

from .schema import MODEL_COLUMNS, TABLE_COLUMNS


def result_to_json_bytes(result: dict[str, Any]) -> bytes:
    return json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")


def result_to_excel_bytes(result: dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        project = result.get("project", {})
        pd.DataFrame([project]).to_excel(writer, index=False, sheet_name="project")
        for table_key, columns in TABLE_COLUMNS.items():
            pd.DataFrame(result.get(table_key, []), columns=columns).to_excel(
                writer, index=False, sheet_name=table_key[:31]
            )
        pd.DataFrame(
            result.get("white_box_model", []), columns=MODEL_COLUMNS
        ).to_excel(writer, index=False, sheet_name="white_box_model")
        pd.DataFrame(
            [{"optimization_summary": result.get("optimization_summary", "")}]
        ).to_excel(writer, index=False, sheet_name="optimization")
        pd.DataFrame([{"result_analysis": result.get("result_analysis", "")}]).to_excel(
            writer, index=False, sheet_name="analysis"
        )
        pd.DataFrame(result.get("improvement_evidence", [])).to_excel(
            writer, index=False, sheet_name="improvement"
        )
    return buffer.getvalue()


def result_to_csv_zip_bytes(result: dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "project.csv",
            pd.DataFrame([result.get("project", {})]).to_csv(index=False),
        )
        for table_key, columns in TABLE_COLUMNS.items():
            archive.writestr(
                f"{table_key}.csv",
                pd.DataFrame(result.get(table_key, []), columns=columns).to_csv(
                    index=False
                ),
            )
        archive.writestr(
            "white_box_model.csv",
            pd.DataFrame(result.get("white_box_model", []), columns=MODEL_COLUMNS).to_csv(
                index=False
            ),
        )
        archive.writestr(
            "improvement_evidence.csv",
            pd.DataFrame(result.get("improvement_evidence", [])).to_csv(index=False),
        )
    return buffer.getvalue()
