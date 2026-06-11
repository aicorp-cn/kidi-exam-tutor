# Changelog

## v5.3 — 2026-06-07

### 健壮性

- **Stage 2 工具自选**：`tool_choice` 从预设单一工具改为 `"required"` + 全 5 个工具。
  LLM 根据实际数据选择正确的题型工具，自动纠正 Stage 1 可能的 `exam_type` 误判。
- **语义校验**：新增 `_validate_semantic()`，在 Store 前逐题比对 Stage 1 题干关键短语
  与 Stage 2 精讲文本。未命中 → `warnings`。信号不阻断管线。
- **RuntimeError 拆分**：`EMPTY_EXAM`/`PASSAGE_ONLY`/`OPEN_ENDED_UNSUPPORTED` → `recoverable=True` + 中文提示；
  `BAD_EXAM_TYPE` → `recoverable=False`；其他 → 系统错误。

### 配置

- `extra_body` 从 engine.py 硬编码 → `config.yaml` 的 `llm.stage1.extra_body` 可配。
  `config.py::llm_for()` 透传 `extra_body` 字段。
- `config.yaml` 中 `stage1.extra_body.thinking.type: "disabled"` 记录模型配方。

## v5.2 — 2026-06-07

### Stage 1

- `deepseek-v4-flash` thinking mode 默认开启，与 `tool_choice` 冲突（400）。
  通过 `extra_body={"thinking": {"type": "disabled"}}` 解决。

### 安全加固

- 用户端错误消息三层泛化（500/429/其他），技术细节仅写入 `pipeline.log`
- `/health?deep=true` 追加 `llm_reachable`，零模型名泄露
- 模型名正则门禁 `^[a-zA-Z][a-zA-Z0-9.\-_]+$`

## v5.1 — 2026-06-06

### 配置系统

- `config.yaml` 作为唯一事实源，YAML → `Config` 单例
- 两级 LLM 参数覆盖：全局 → pipeline 默认 → Stage 覆盖
- 三层门禁：启动（`exit 1`）/ 运行时（SSE error）/ 健康（`/health`）
- `/api/config` 前端动态配置端点

### 前后端协同

- 前端 onload 从 `/api/config` 获取 `page_size`、`allowed_types` 等动态常量

## v5.0 — 2026-06-05

### 架构：Tool Calling + Strict Schema

- Stage 1 `parse_exam` Tool (strict: true) → 结构化试卷解析
- Stage 2 5 个 Tool (strict: true) → 逐题精讲生成
- Beta endpoint (`https://api.deepseek.com/beta`) + 降级方案

### 数据契约

- `ReviewData` 统一渲染入口，`reviewDataFromSSE` / `reviewDataFromDB` 双适配器

### Variant 系统

- `detect_variant()` 纯函数判定 `multiple_choice` / `open_ended` / `empty` / `passage_only`

### 管线可观测性

- `pipeline_log.py` JSON Lines → `data/pipeline.log`

### 前端

- 三屏幕 SPA（Home → Processing → Review）
- PWA 支持、TTS 朗读、原文溯源、横滑翻页

## v4.x — 2026-06-03

- `response_format: json_object` → LLM 输出 JSON
- 后端 `validate_stage2()` 抓结构错误
- 题型模板是 User Prompt 文本

## v1-v3 — 2026-06-01 ~ 2026-06-02

- `parse_exam.py` 文本解析脚本（518行，3 题型 × 3 测试用例）
- OCR → 文本 → Agent 执行的初始管线
- `ocr-and-documents` Skill 探索（确定不可用于 JPEG 试卷）
- 确定 DeepSeek Tool Calling + Strict Schema 架构方向
