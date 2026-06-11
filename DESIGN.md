# Exam Tutor — 架构设计

> v5.3 | Tool Calling + Strict Schema + 工具自选 + 语义校验

## 目录

1. [设计原则](#1-设计原则)
2. [系统架构](#2-系统架构)
3. [管线](#3-管线)
4. [Tool 系统](#4-tool-系统)
5. [数据契约](#5-数据契约)
6. [SSE 事件协议](#6-sse-事件协议)
7. [前端架构](#7-前端架构)
8. [Variant 系统](#8-variant-系统)
9. [配置系统](#9-配置系统)
10. [可观测性](#10-可观测性)
11. [安全边界](#11-安全边界)

---

## 1. 设计原则

| # | 原则 | 实现 |
|---|------|------|
| 1 | **后端产出已验证的结构化数据，前端只做渲染** | ReviewData 契约 + 双适配器 |
| 2 | **LLM 的不确定性用架构约束对冲** | Strict Schema + 工具自选 + 语义校验 |
| 3 | **三层 Schema 保证** | Tool JSON Schema → Tool description → System Prompt |
| 4 | **信息边界** | 用户端无模型名、无 API 错误详情、无 endpoint |
| 5 | **质量门分层** | OCR 质量门（硬阻断）/ 结构校验（strict 保证）/ 语义校验（warnings 不阻断） |

---

## 2. 系统架构

### 2.1 组件拓扑

```
┌─────────────────────────────────────────────────────┐
│                    FastAPI :8080                      │
│                                                       │
│  POST /exams (images)                                 │
│       │                                               │
│       ▼                                               │
│  ┌─────────┐    ┌──────────┐    ┌──────────┐         │
│  │  OCR    │───▶│ Stage 1  │───▶│ Stage 2  │         │
│  │tesseract│    │v4-flash  │    │deepseek  │         │
│  │ 5.5 CLI │    │+ thinking│    │ -chat    │         │
│  │         │    │ =disabled│    │+ 5 tools │         │
│  └─────────┘    └──────────┘    └──────────┘         │
│       │               │               │               │
│       ▼               ▼               ▼               │
│  pipeline.log ◄── pipeline_log ◄── _validate         │
│                                          │            │
│  SQLite ◄──────── store ◄───────────────┘            │
│                                          │            │
│  GET /sse/ui?session=X ◄────────────────┘            │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────┐
│   webui/     │
│  index.html  │  SPA (Home / Processing / Review)
│  sw.js       │  PWA Service Worker
│  manifest.js │
└──────────────┘
```

### 2.2 技术选型

| 组件 | 技术 | 约束 |
|------|------|------|
| 运行时 | Python 3 + FastAPI | 单进程 asyncio，ARM SBC 2GB RAM |
| OCR | tesseract 5.5 CLI | 子进程调用，英文语言包 |
| LLM Stage 1 | deepseek-v4-flash | thinking=disabled（兼容 tool_choice） |
| LLM Stage 2 | deepseek-chat | tool_choice="required"，5 工具自选 |
| API | OpenAI-compatible SDK | Strict Mode → Beta endpoint |
| 存储 | SQLite | 单表，WAL 模式 |
| 前端 | 原生 HTML/CSS/JS | 零框架依赖，PWA |
| 日志 | JSON Lines | pipeline.log，按 session_id 可检索 |

### 2.3 文件结构

```
exam-tutor/
├── agent/                   # 后端
│   ├── main.py              # FastAPI 入口 + API + SSE
│   ├── engine.py            # 管线编排 (OCR → S1 → S2 → Store)
│   ├── ocr.py               # tesseract CLI 封装 + 质量门
│   ├── tools.py             # 6 个 Tool Definition + 路由表
│   ├── prompts.py           # System/User Prompts
│   ├── store.py             # SQLite CRUD
│   ├── pipeline_log.py      # JSON Lines 管线日志
│   ├── config.py            # YAML 加载 + 门禁 + 参数合并
│   └── requirements.txt     # Python 依赖
├── webui/                   # 前端
│   ├── index.html           # SPA（三屏幕 + TTS + 原文溯源）
│   ├── sw.js                # PWA Service Worker
│   ├── manifest.json        # PWA Manifest
│   └── icons/               # PWA 图标
├── data/                    # 运行时数据（gitignore）
│   ├── exams.db             # SQLite 数据库
│   └── pipeline.log         # 管线日志
├── config.yaml              # 唯一配置事实源
├── start.sh                 # 一键启动（含预检）
├── .env.example             # 环境变量模板
├── .gitignore
├── README.md
├── CHANGELOG.md
└── DESIGN.md                # 本文件
```

---

## 3. 管线

### 3.1 完整流程

```
POST /exams (images[])
  │
  ├─ 1. 接收 & 验证
  │     └─ 文件类型白名单、大小限制
  │
  ├─ 2. OCR (tesseract CLI)
  │     ├─ 逐页识别，=== PAGE N/M === 拼接
  │     └─ 质量门：空文本 / 过短 / 英文占比 < 30% → 硬阻断
  │
  ├─ 3. Stage 1 — 试卷结构化解析
  │     ├─ Model: deepseek-v4-flash
  │     ├─ extra_body: {thinking: {type: disabled}}
  │     ├─ tool_choice: parse_exam
  │     ├─ strict: true
  │     └─ 产出: {exam_type, passage, questions[]}
  │
  ├─ 4. detect_variant(s1_data)
  │     └─ 纯函数：判断 multiple_choice / open_ended / empty / passage_only
  │
  ├─ 5. Stage 2 — 逐题精讲
  │     ├─ Model: deepseek-chat
  │     ├─ tool_choice: "required" (LLM 从 5 工具自选)
  │     ├─ strict: true
  │     └─ 产出: {questions[{number, answer, modules}]}
  │
  ├─ 6. 校验
  │     ├─ 题数软校验（S1 vs S2 question_count）
  │     ├─ _validate_semantic() — 逐题比对题干关键短语
  │     └─ warnings 不阻断，透传到前端
  │
  └─ 7. Store → SSE stage2/done
```

### 3.2 Stage 2 截断处理

`finish_reason == "length"` 时自动分片：

1. 首次截断 → 按 2 题一批分片
2. 每批独立调用 Stage 2（保留原 `passage`）
3. 合并所有批次（按题号排序）
4. 单批仍截断 → 单独重试 1 次

配合 `max_tokens=16384` 和 MODULE QUALITY prompt（信息槽位约束，非字数上限）三层协同。

### 3.3 重试策略

| 条件 | 行为 |
|------|------|
| `tool_calls` 为空 | 重试（最多 2 次） |
| JSON 解析失败 | 重试 |
| JSON recovered（截断修复） | 重试获取完整数据 |
| API Timeout / Rate Limit (429) | 重试 |
| API 500+ | 重试 |
| Strict Mode 不可用 (4xx, 非429) | `_maybe_fallback` → 非 beta endpoint |

### 3.4 语义校验 (v5.3)

`_validate_semantic(s1_data, s2_data)` — Store 前逐题比对：

1. 从 S1 `sentence_with_blank` / `stem` / `statement` 提取最长英文词序列（3-5 词）
2. 在 S2 `modules` 全部文本中搜索
3. 未命中 → `warnings.append("第N题精讲未基于正确题干...")`
4. **信号不阻断** — 写入 warnings，透传到前端

---

## 4. Tool 系统

### 4.1 设计原理

题型契约是**系统级实体**，编码在 Tool Definition 的三层结构中：
- **JSON Schema**（API 强制，`strict: true` + `additionalProperties: false`）
- **Tool description**（LLM 路由依据）
- **System Prompt**（行为约束）

v5.3 关键改进：Stage 2 的 `tool_choice` 从预设单一工具改为 `"required"` + 全 5 工具，LLM 根据数据自选——自动纠正 Stage 1 可能的 `exam_type` 误判。

### 4.2 Stage 1: `parse_exam`

将 OCR 文本解析为结构化 JSON：

- `exam_type`: `grammar_cloze` / `cloze` / `reading_comp` / `true_false`
- `passage`: 完整文章文本
- `questions[]`: 每题含 `id`, `context_before`, `sentence_with_blank`, `context_after`, `options{A,B,C,D}`, `stem`, `statement`
- 非适用字段填空字符串（Strict Mode 要求全部 required）

### 4.3 Stage 2: 5 个 Tool

| Tool | 题型 | 精讲模块 |
|------|------|---------|
| `generate_grammar_cloze` | 语法选择 | 上下文 / 生词洞察 / 选项词义 / 考点 / 解析 / 排除法 |
| `generate_cloze` | 完形填空 | 同上（Schema 共享） |
| `generate_open_cloze` | 开放型填空 | 上下文 / 生词洞察 / 考点 / 解析 / 推断思路 |
| `generate_reading_comp` | 阅读理解 | 题干定位 / 选项词义 / 考点 / 解析 / 排除法 |
| `generate_true_false` | 正误判断 | 原句·题干 / 原文依据 / 考点 / 解析 |

### 4.4 路由表

```python
STAGE2_TOOL_NAME = {
    "grammar_cloze": "generate_grammar_cloze",
    "cloze": "generate_cloze",
    "reading_comp": "generate_reading_comp",
    "true_false": "generate_true_false",
}

VARIANT_TOOL_NAME = {
    ("grammar_cloze", "open_ended"): "generate_open_cloze",
    ("cloze", "open_ended"): "generate_open_cloze",
}
```

### 4.5 Prompts 设计

**Stage 1 System Prompt** (~150 tokens)：考试文本解析器，查找 blank（`___N___`）、跨页匹配选项、容忍 OCR 噪声。

**Stage 2 System Prompt** (~200 tokens)：初中英语辅导老师。
- 规则 1-4：通用格式（音标 `／／`、`<u>` 标记答案、排除法原因分类、显式公式）
- 规则 5：**MODULE QUALITY** — 每模块信息槽位模板（非字数上限）
  - 考点：`[触发条件] + [→] + [答案形式]`
  - 解析：`[上下文线索] → [规则/推理] → [结论]`
  - 排除法：9 类可证伪原因（时态错误/语态错误/词性不符/搭配不当/意思不对/主谓不一致/无中生有/与原文相反/过度推断）
  - 各题型专属模块均有对应槽位指南
- 规则 6：仅输出函数调用

**User Prompt**：Stage 1 = `OCR TEXT:\n{ocr_text}` + 多页标记；Stage 2 = `Passage:\n{passage}\n\nQuestions:\n{q_block}`。

---

## 5. 数据契约

### 5.1 ReviewData — 前端统一渲染入口

```typescript
ReviewData = {
  questions: Array<{number: int, answer: string, modules: object}>,
  exam_id: string,
  exam_type: string,      // grammar_cloze | cloze | reading_comp | true_false
  variant: string,        // multiple_choice | open_ended
  passage: string,        // Stage 1 完整文章
  s1_questions: Array,    // Stage 1 原始 questions（原文溯源）
  warnings: string[],
}
```

两个适配器：
- `reviewDataFromSSE(d)` — SSE `stage2/done` → ReviewData
- `reviewDataFromDB(e)` — DB 记录 → ReviewData

所有 Review 渲染通过 `renderReviewData(rd)` 统一入口。

### 5.2 DB Schema

```sql
CREATE TABLE exams (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    exam_type TEXT NOT NULL DEFAULT '',
    variant TEXT NOT NULL DEFAULT '',
    passage TEXT NOT NULL DEFAULT '',
    s1_questions TEXT NOT NULL DEFAULT '',   -- JSON
    question_count INTEGER NOT NULL DEFAULT 0,
    ocr_text TEXT NOT NULL DEFAULT '',
    tutorial TEXT NOT NULL DEFAULT '',       -- JSON
    warnings TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

索引：`session_id`、`created_at DESC`。WAL 模式。

---

## 6. SSE 事件协议

```
connected    → {stage:"connected", session:".."}
ocr          → {stage:"ocr", status:"start", files:N}
             → {stage:"ocr", status:"done", method:"tesseract", chars:N}
stage1       → {stage:"stage1", status:"start"}
             → {stage:"stage1", status:"done", exam_type:"..", question_count:N, variant:".."}
stage2       → {stage:"stage2", status:"start", question_count:N}
             → {stage:"stage2", status:"done", questions:[...], exam_id:"..", warnings:[...]}
error        → {stage:"error", status:"ocr_failed"|"api_error"|"unknown", message:"..", recoverable:bool}
```

Heartbeat：Stage 2 调用期间每 5 秒发送 progress 事件。SSE 重连：前 2 次静默，第 3 次弹框。

---

## 7. 前端架构

### 7.1 三屏幕

| 屏幕 | 触发 | 内容 |
|------|------|------|
| Home | 默认 | 拍照/相册、Ctrl+V 粘贴、历史列表（分页加载） |
| Processing | 上传成功 | 管线步骤实时状态（上传→识别→精讲） |
| Review | SSE done 或历史点击 | 题目卡片 + 横滑翻页 + 底部导航 |

### 7.2 题目卡片

- 模块按 `MODULE_ORDER` 表确定的顺序渲染
- 默认展开：解析、上下文、题干定位、原句/题干、推断思路
- 默认折叠：生词洞察、选项词义、考点、排除法
- 点击模块标题切换展开/折叠

### 7.3 原文溯源

- **记录级**：`passage`（可折叠 `📄 原文` + 🔊 TTS）
- **题目级**：`s1_questions[i]`（可折叠 `📎 原始文本`，monospace 字体保留 OCR 噪声）

### 7.4 TTS 朗读

三层触发：
- **L1 自动序列**：▶ 按钮，按题型决定模块序列
- **L2 手动模块**：每模块 🔊 按钮
- **L3 原文**：📄 旁 🔊 按钮

文本切分：状态机按 `[a-zA-Z]+`（en-US）、`[\u4e00-\u9fff]+`（zh-CN）、`/.../`（音标→跳过）分段。缺失语音包时按钮禁用并提示。

### 7.5 图片预处理

前端执行：`maxSide=1920` 等比缩放 + JPEG quality 0.8。失败分多级阻断（格式不支持/过大/处理失败）。

### 7.6 PWA

- Service Worker 缓存静态资源
- `manifest.json` + 图标（192/512）
- 离线可访问已缓存页面

---

## 8. Variant 系统

### 8.1 判定

`detect_variant(s1_data)` — 纯函数，检查所有题目的 options 是否全空。

```
multiple_choice — 标准选择题
open_ended      — 所有题 options 全空
empty           — 无 passage 无 questions
passage_only    — 有 passage 无 questions
```

### 8.2 路由

| exam_type | variant | Tool |
|-----------|---------|------|
| grammar_cloze / cloze | multiple_choice | generate_grammar_cloze / generate_cloze |
| grammar_cloze / cloze | open_ended | generate_open_cloze |
| reading_comp / true_false | multiple_choice | generate_reading_comp / generate_true_false |
| reading_comp / true_false | open_ended | 报错：OCR 识别问题，请重新拍摄 |

### 8.3 前端表现

`open_ended`：Review 顶部显示 variant banner，答案模块显示 AI 推断答案。`variant` 入库，历史列表显示标签。

---

## 9. 配置系统

### 9.1 文件关系

```
config.yaml   ← 唯一事实源（所有可配置参数）
.env          ← 密钥（gitignore）
config.py     ← 加载器 + 门禁 + 两级 LLM 覆盖
```

### 9.2 加载优先级

```
环境变量 > config.yaml > 代码默认值
```

### 9.3 LLM 参数两级覆盖

```
llm:                        ← 全局（所有 Stage 继承）
  model: "deepseek-chat"
  base_url: ...
  retry_attempts: 2

  stage1:                   ← Stage 覆盖
    model: "deepseek-v4-flash"
    temperature: 0.0
    extra_body: {thinking: {type: disabled}}

  stage2:                   ← Stage 覆盖
    temperature: 0.3
    max_tokens: 16384
```

`config.llm_for("stage1")` 返回合并后的扁平 dict。

### 9.4 门禁分层

| 层级 | 时机 | 检测项 | 失败结果 |
|:--:|------|------|------|
| 启动 | uvicorn.run 前 | Schema 合规、API key 存在、路径可写、值域合法 | `exit(1)` + 中文 |
| 运行时 | 首 LLM 调用 | base_url 可达性、model 有效性 | SSE error |
| 健康 | 任意时刻 | `/health` 端点 | JSON status |

### 9.5 前后端协同

前端 onload 时 `fetch('/api/config')` 获取 `upload_max_mb`、`allowed_types`、`page_size`、`api_base`，动态注入 `<input accept>`、分页大小、API URL。

---

## 10. 可观测性

### 10.1 管线日志

JSON Lines → `data/pipeline.log`。每行 `{step, session_id, ts, ...}`。

| 事件 | 内容 |
|------|------|
| upload | file_count, total_bytes |
| ocr_start / ocr_result | method, duration_ms, text_length, success |
| stage1_entry / stage1_result | q_count, exam_type, success/error |
| variant_detect | variant, exam_type |
| llm_start / llm_result | ocr_text_length, model, duration_ms, success |
| retry | stage, attempt, reason |

### 10.2 健康检查

```
GET /health          → {status, checks, version}
GET /health?deep=true → 追加 llm_reachable (bool)
```

零模型名泄露。`/api/config` 仅返回前端所需参数，无密钥。

### 10.3 错误收集

`POST /debug/client-error` — 浏览器端 JS 错误收集端点。

---

## 11. 安全边界

| 边界 | 措施 |
|------|------|
| 模型名 | 不出现于 SSE / `/health` / `/api/config` / 用户端错误消息 |
| API 错误详情 | `_api_error_detail()` → `pipeline.log`；用户端三类泛化消息（500/429/其他） |
| endpoint | 不出现在用户可见消息中 |
| API Key | 仅从环境变量读取，`.env` gitignore |
| 模型名注入 | 正则门禁 `^[a-zA-Z][a-zA-Z0-9.\-_]+$`，三层校验 |
| deep model ping | `validate(deep=True)` 通过 1-token ping 验证模型可达性 |

---

> 版本演进历史：[CHANGELOG.md](CHANGELOG.md)
