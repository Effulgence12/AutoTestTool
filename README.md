# AutoTestDesign Tool

这是软件测试 Assignment 2 中的 AI-driven AutoTestDesign 工具。工具使用 Streamlit 构建界面，并通过阿里云 DashScope OpenAI-compatible endpoint 真实调用 Qwen 模型生成测试设计产物。

## 功能覆盖

- FR1.0：支持文本、TXT、CSV 需求输入。
- FR1.1：调用 Qwen 提取结构化需求字段。
- FR2.0：生成风险分数、优先级和风险理由。
- FR3.0：生成等价类划分、边界值分析、决策表三类黑盒测试用例。
- FR4.0：轻量生成状态/控制流模型和覆盖序列。
- FR5.0：为测试用例生成 expected result / oracle。
- FR6.0：导出 JSON、CSV ZIP、Excel。
- FR7.0：按风险和覆盖价值给出测试套件优化摘要。
- 交互式审查：可修改结构化需求、覆盖项、策略、测试用例和追溯矩阵，并生成改进证据。
- 审查质量门禁：新增/修改/删除会生成字段级改进证据；导出前会检查空测试用例字段和缺失追溯关系。

## 安装

```powershell
cd .\AutoTestTool
conda create <虚拟环境名> -y python=3.11 pip
conda activate <虚拟环境名>
python -m pip install -r requirements.txt
```

## 配置

`.env` 中至少填写一个 API key：

```env
ENABLE_LLM=1
QWEN_API_KEY=your_key
DASHSCOPE_API_KEY=
QWEN_MODEL=qwen3.5-plus-2026-04-20
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=8192
LLM_TIMEOUT_SECONDS=180
QWEN_ENABLE_THINKING=0
```

工具不会使用本地假数据降级。若 API key、模型名、网络或 JSON 返回异常，界面会显示真实错误。
`QWEN_ENABLE_THINKING=0` 用于关闭 Qwen3.5 的深度思考模式，减少课堂演示中的等待时间；如需更强推理可改为 `1`。

## 运行

```powershell
conda activate <虚拟环境名>
python -m streamlit run app.py
```

打开 Streamlit 显示的本地地址后：

1. 输入目标应用名称和模块名称。
2. 粘贴需求文本，或上传 TXT/CSV。
3. 点击“验证 Qwen 配置”确认 API 可用。
4. 点击“生成测试设计”。
5. 在各个可编辑表格中审查并修改覆盖项、策略、测试用例和追溯矩阵。
6. 在“改进证据区”为新增或修改填写 `reason` 和 `gap_identified`，作为人工审查证据。
7. 确认“导出前质量检查”没有空用例字段或缺失追溯。
8. 导出 JSON、CSV ZIP 或 Excel，用于报告和演示。

## 演示需求示例

```text
用户登录时，用户名必须为 6-20 个字符，只允许字母、数字和下划线。
密码不能为空，长度必须至少 8 个字符。
用户名或密码错误时显示错误提示。
连续 5 次登录失败后账号锁定 10 分钟。
锁定期间再次登录时应显示账号锁定信息。
```

## 性能说明

工具主流程尽量通过一次 Qwen 调用生成完整 JSON，以减少延迟并接近“测试用例生成时间不超过 2 秒”的目标。真实耗时取决于网络、模型负载、需求长度和 `LLM_MAX_TOKENS`。若演示环境中超过 2 秒，应在报告中记录实际耗时、原因和改进建议，例如缩短输入、减少生成行数、使用更快模型或缓存中间结果。
