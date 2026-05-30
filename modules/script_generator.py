from __future__ import annotations

import re
from typing import Any


def add_generated_scripts(result: dict[str, Any]) -> dict[str, Any]:
    result["generated_pytest"] = generate_pytest_script(result)
    result["generated_selenium"] = generate_selenium_script(result)
    return result


def generate_pytest_script(result: dict[str, Any]) -> str:
    lines = [
        '"""Generated pytest template from AutoTestDesign.',
        "Fill in target-application calls and assertions before real execution.",
        '"""',
        "",
        "import pytest",
        "",
        "",
    ]
    for test_case in result.get("test_cases", []):
        function_name = function_name_for(test_case.get("test_case_id", "test_case"))
        lines.extend(
            [
                f"def test_{function_name}():",
                f"    # Technique: {test_case.get('technique', '')}",
                f"    # Test data: {test_case.get('test_data', '')}",
                f"    # Steps: {test_case.get('steps', '')}",
                f"    # Expected: {test_case.get('expected_result', '')}",
                "    # TODO: call the target application and assert the expected result.",
                "    assert True",
                "",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def generate_selenium_script(result: dict[str, Any]) -> str:
    lines = [
        '"""Generated Selenium template from AutoTestDesign.',
        "Replace selectors and URL with the target application's real UI.",
        '"""',
        "",
        "from selenium import webdriver",
        "from selenium.webdriver.common.by import By",
        "",
        "",
        "def build_driver():",
        "    return webdriver.Chrome()",
        "",
        "",
    ]
    for test_case in result.get("test_cases", []):
        function_name = function_name_for(test_case.get("test_case_id", "test_case"))
        lines.extend(
            [
                f"def test_{function_name}_selenium():",
                "    driver = build_driver()",
                "    try:",
                "        # TODO: driver.get('http://localhost:YOUR_PORT')",
                f"        # Technique: {test_case.get('technique', '')}",
                f"        # Test data: {test_case.get('test_data', '')}",
                f"        # Steps: {test_case.get('steps', '')}",
                f"        # Expected: {test_case.get('expected_result', '')}",
                "        assert True",
                "    finally:",
                "        driver.quit()",
                "",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def function_name_for(test_case_id: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_]+", "_", test_case_id.strip().lower())
    cleaned = cleaned.strip("_") or "test_case"
    if cleaned[0].isdigit():
        cleaned = "tc_" + cleaned
    return cleaned
