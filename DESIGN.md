# Exam Tutor v5.3 — Tool Calling + Strict Schema + Auto-Correction

## 〇、v4 → v5 的范式转换

| v4 | v5 |
|----|----|
| `response_format: json_object` → LLM 输出 JSON | `tools` + `strict: true` → API 强制 Schema 合规 |
| 后端 `validate_stage2()` 抓结构错误 | 结构由 API 保证，后端只做语义校验 |
| 校验失败 → 追加 User message 重试 | Strict Mode 下 LLM 无法产出不合规输出 |
| 题型模板是 User Prompt 文本 | 题型模板是 Tool Definition 的 JSON Schema + description |
| "契约"存在于 Python dataclass | "契约"存在于 API 调用参数 + 语义校验锚点 |

> **v5.3 关键改进**：Stage 2 `tool_choice` 从预设单一工具改为 `"required"` + 全 5 个工具。
> LLM 根据数据选择题型工具——自动纠正 Stage 1 可能的 `exam_type` 误判。
> 追加 `_validate_semantic()` 语义校验（逐题比对题干关键短语 vs 精讲文本），不阻断管线但写入 warnings。

## 一、技术基础：DeepSeek Tool Calling + Strict Mode

### 1.1 三个关键机制

```json
{
  "type": "function",
  "function": {
    "name": "generate_grammar_cloze",
    "strict": true,
    "description": "...",
    "parameters": { /* JSON Schema */ }
  }
}
```

- **`strict: true`**：API 强制 LLM 输出严格匹配 JSON Schema。所有 properties 必须 `required`，`additionalProperties: false`。
- **`tool_choice`**：Stage 1 预设 `parse_exam`；Stage 2 使用 `"required"` + 全 5 工具，LLM 自选。
- **`base_url="https://api.deepseek.com/beta"`**：Strict Mode 是 Beta 功能，需要 Beta endpoint。
- **`extra_body={"thinking": {"type": "disabled"}}`**：`deepseek-v4-flash` 默认启用 thinking mode，与 `tool_choice` 冲突。通过 `config.yaml` 的 `llm.stage1.extra_body` 禁用。

### 1.2 降级方案

Strict Mode 不可用时：

```
Strict Mode (beta) → response_format: json_object + 后端结构校验
```

### 1.3 OCR 质量门

| 检查项 | 阈值 | 失败处理 |
|--------|------|---------|
| 空文本 | len == 0 | 报错，提示 + 已成功页数 |
| 过短文本 | < 50 chars | 报错，提示 + 已成功页数 |
| 英文字符占比 | < 30% | 报错（硬阻断），提示"请确认是英文试卷" |

每个质量门报错时包含「前 N 页已成功」信息，学生只需重拍失败页。

## 二、Tool 定义（tools.py）

### 2.1 Stage 1：`parse_exam`

将 OCR 文本解析为结构化 JSON：

- `exam_type`：`grammar_cloze` / `cloze` / `reading_comp` / `true_false`
- `passage`：完整文章文本
- `questions[]`：每题含 `id`, `context_before`, `sentence_with_blank`, `context_after`, `options{A,B,C,D}`, `stem`, `statement`
- 非适用字段填空字符串（Strict Mode 要求所有字段 required）

### 2.2 Stage 2：5 个 Tool

| Tool | 题型 | 模块 |
|------|------|------|
| `generate_grammar_cloze` | 语法选择 | 上下文、生词洞察、选项词义、考点、解析、排除法 |
| `generate_cloze` | 完形填空 | 同上（Schema 共享） |
| `generate_open_cloze` | 开放型填空 | 上下文、生词洞察、考点、解析、推断思路 |
| `generate_reading_comp` | 阅读理解 | 题干定位、选项词义、考点、解析、排除法 |
| `generate_true_false` | 正误判断 | 原句/题干、原文依据、考点、解析 |

### 2.3 路由表

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

## 三、Prompts（prompts.py）

### 3.1 Stage 1 System Prompt

- 角色：考试文本解析器
- 规则：查找 blank（`___N___`）、跨页匹配选项、容忍 OCR 噪声
- ~150 tokens

### 3.2 Stage 2 System Prompt

- 角色：初中英语辅导老师
- 优先级：准确 > 认知负荷 > 信息密度（成本函数驱动，非字数驱动）
- 规则 1-4：通用格式（音标 `／／`、`<u>` 标记答案、排除法原因分类、显式公式）
- 规则 5：MODULE QUALITY — 每模块的信息槽位模板（非字数上限）
  - 考点（all types）：`[触发条件] + [→] + [答案形式]`
  - 解析（all types）：`[上下文线索] → [规则/推理] → [结论]`
  - 排除法（有选项的题型）：9 类可证伪原因（时态错误/语态错误/词性不符/搭配不当/意思不对/主谓不一致/无中生有/与原文相反/过度推断）
  - 各题型专属模块（题干定位/原文依据/原句·题干/推断思路）均有对应槽位指南
  - 生词洞察、选项词义：精选高频词/上下文含义，非穷举
- 规则 6：仅输出函数调用

### 3.3 用户 Prompt 构建

- Stage 1：`OCR TEXT:\n{ocr_text}` + 多页标记 `({page_count} pages)`
- Stage 2：`Passage:\n{passage}\n\nQuestions (N total):\n{q_block}` + open_ended 时追加中文提示

## 四、管线（engine.py）

### 4.1 流程

```
POST /exams (images)
  → OCR (tesseract, === PAGE N/M === 拼接 + 质量门)
  → Stage 1: tool_choice=parse_exam + extra_body(thinking=disabled)
      → 产出 {exam_type, passage, questions[...]}
  → detect_variant(s1_data) — 纯函数，无 LLM
  → Stage 2: tool_choice="required" + 全 5 工具 (模型自选)
      → 产出 {questions[{number, answer, modules}]}
  → 题数软校验 + _validate_semantic (warnings 不阻断)
  → Store → SSE stage2/done
```

### 4.2 JSON 解析

- **Stage 1**：`_parse_json()` — 从 `tool_calls[0].function.arguments` 解析
- **Stage 2**：同上，容错 trailing data 用 `raw_decode()`

### 4.3 重试策略

- `tool_calls` 为空 → 重试（最多 2 次）
- JSON 解析失败 → 重试
- JSON recovered（截断修复）→ 重试获取完整数据
- API Timeout / Rate Limit → 重试
- API 500+ → 重试
- Strict Mode 不可用 → `_maybe_fallback` 切换到非 beta endpoint

### 4.4 语义校验（v5.3）

`_validate_semantic(s1_data, s2_data)` — Store 前逐题比对：

1. 从 Stage 1 `sentence_with_blank` / `stem` / `statement` 提取最长英文词序列（3-5 词）
2. 在 Stage 2 `modules` 的全部文本中搜索
3. 未命中 → `warnings.append("第N题精讲未基于正确题干...")`
4. 信号不阻断——写入 warnings 透传到前端

### 4.5 Heartbeat

Stage 2 LLM 调用期间（可能 30-60s）每 5 秒发送 progress 事件。

### 4.6 变种检测（detect_variant）

```python
def detect_variant(s1_data) -> str:
    # "multiple_choice" — 标准选择题
    # "open_ended" — 所有题 options 全空
    # "empty" — 无 passage 无 questions
    # "passage_only" — 有 passage 无 questions
```

### 4.7 Stage 2 截断处理

当 `finish_reason == "length"` 时，自动将题目分批重新生成：

1. 首次截断 → 按 2 题一批分片
2. 每批独立调用 Stage 2（保留原 `passage`）
3. 合并所有批次结果（按题号顺序）
4. 若单批仍截断（极端情况）→ 单独重试 1 次

此机制配合 `max_tokens=16384` 和 MODULE QUALITY prompt（§3.2 规则 5）共同作用：
- **Prompt 层**：减少非必要膨胀（信息槽位约束，非字数上限）
- **检测层**：`finish_reason == "length"` 捕获截断
- **恢复层**：分片重试，不丢题

## 五、SSE 事件协议

```
connected    → {"stage":"connected","session":".."}
ocr          → {"stage":"ocr","status":"start","files":2}
             → {"stage":"ocr","status":"done","method":"tesseract","chars":1427}
stage1       → {"stage":"stage1","status":"start"}
             → {"stage":"stage1","status":"done","exam_type":"grammar_cloze","question_count":10,"variant":"multiple_choice"}
stage2       → {"stage":"stage2","status":"start","question_count":10}
             → {"stage":"stage2","status":"done","questions":[...],"exam_id":"..","exam_type":"..","variant":"..","passage":"...","s1_questions":[...],"warnings":[...]}
error        → {"stage":"error","status":"ocr_failed"|"api_error"|"unknown","message":"..","recoverable":bool}
```

## 六、DB Schema（store.py）

```sql
CREATE TABLE exams (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    exam_type TEXT NOT NULL DEFAULT '',
    variant TEXT NOT NULL DEFAULT '',
    passage TEXT NOT NULL DEFAULT '',
    s1_questions TEXT NOT NULL DEFAULT '',    -- JSON: Stage 1 questions 数组
    question_count INTEGER NOT NULL DEFAULT 0,
    ocr_text TEXT NOT NULL DEFAULT '',
    tutorial TEXT NOT NULL DEFAULT '',        -- JSON: Stage 2 questions 数组
    warnings TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

索引：`session_id`、`created_at DESC`。

## 七、API Endpoints（main.py）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/exams` | POST | 上传图片 → 返回 session_id → 启动异步管线 |
| `/exams` | GET | 分页历史列表（`?page=1&limit=20`） |
| `/exams/{id}` | GET | 单条完整记录 |
| `/sse/ui?session=X` | GET | SSE 事件流 |
| `/debug/client-error` | POST | 浏览器端 JS 错误收集 |

## 八、前端设计（webui/index.html）

### 8.1 核心原则

> **所有渲染路径共享统一入口 `renderReviewData(rd)`。** SSE live 和 REST 历史路径各有一个适配器，产出相同形状的 `ReviewData` 对象。

### 8.2 三屏幕

| 屏幕 | 触发 | 内容 |
|------|------|------|
| Home | 默认 | 拍照/相册按钮、Ctrl+V 粘贴、分页历史列表 |
| Processing | 上传成功后 | 管线步骤（上传→识别→精讲）、实时状态 |
| Review | SSE done 或历史点击 | 题目卡片（横滑翻页）+ 底部导航 |

### 8.3 题目卡片

- 模块按题型确定的顺序渲染（`MODULE_ORDER` 表）
- 默认展开：解析、上下文、题干定位、原句/题干、推断思路
- 默认折叠：生词洞察、选项词义、考点、排除法
- 点击模块标题切换展开/折叠（CSS grid-template-rows 动画）

### 8.4 翻页

- 移动端：左右滑动 ≥ 50px
- 桌面端：键盘 ← →
- 底部导航：上一题/下一题按钮 + 点状页码
- 题目列表 overlay：点击顶部页码弹出

### 8.5 历史列表

- 分页加载（每页 20 条），「加载更多」追加
- 每条显示：相对日期、题型标签、变种标签、N题标签、passage 前 50 字

### 8.6 图片预处理

- `maxSide=1920` 等比缩放 + JPEG quality 0.8
- 失败分多级阻断（格式不支持/过大/处理失败），中文提示
- `toBlob` → `toDataURL` 后备

### 8.7 SSE 重连

- 前 2 次错误静默（允许 EventSource 自动重连）
- 第 3 次错误弹框"连接多次中断，请重试"

### 8.8 文件选择

- `handleFiles` 开头同步执行 `inputEl.value = ''`，确保每次选择均触发 onchange

## 九、ReviewData 渲染数据契约

### 9.1 形状

```typescript
ReviewData = {
  questions: Array<{number: int, answer: string, modules: object}>,
  exam_id: string,
  exam_type: string,          // grammar_cloze|cloze|reading_comp|true_false
  variant: string,            // multiple_choice|open_ended
  passage: string,            // Stage 1 提取的完整文章
  s1_questions: Array,        // Stage 1 原始 questions（用于原文溯源）
  warnings: string[],
}
```

### 9.2 适配器

- `reviewDataFromSSE(d)` — SSE `stage2/done` 事件 → ReviewData
- `reviewDataFromDB(e)` — DB 记录 → ReviewData

### 9.3 统一入口

所有 Review 渲染通过 `renderReviewData(rd)` ——唯一设置 `passageText`、`s1Questions`、调用 `renderCards`、渲染 passage 块和 banner 的地方。

## 十、Variant 系统

### 10.1 变种判定

`detect_variant(s1_data)` — 纯函数，检查所有题目的 options 是否全空。

### 10.2 路由

| exam_type | variant | Tool |
|-----------|---------|------|
| grammar_cloze / cloze | multiple_choice | generate_grammar_cloze / generate_cloze |
| grammar_cloze / cloze | open_ended | generate_open_cloze |
| reading_comp / true_false | multiple_choice | generate_reading_comp / generate_true_false |
| reading_comp / true_false | open_ended | 报错：OCR 识别问题，请重新拍摄 |

### 10.3 前端表现

- `open_ended`：Review 顶部显示 variant banner + 答案模块显示 AI 推断答案
- `variant` 入库并在历史列表显示标签

## 十一、原文溯源

### 11.1 记录级

- 数据源：`passage`（DB 持久化）
- Review 顶部可折叠 `📄 原文`，默认折叠
- 附带 🔊 按钮（TTS 全文朗读）

### 11.2 题目级

- 数据源：`s1_questions[i]`（DB 持久化）
- 每卡底部可折叠 `📎 原始文本`（context_before / sentence_with_blank / context_after）
- 保留 OCR 噪声，monospace 字体如实呈现

### 11.3 数据流

```
SSE live:  SSE stage2/done → passage + s1_questions → renderReviewData
History:   GET /exams/{id} → passage + s1_questions → reviewDataFromDB → renderReviewData
```

两个路径一致。

## 十二、TTS 朗读

### 12.1 文本切分

状态机：按 `[a-zA-Z]+`（en-US）、`[\u4e00-\u9fff]+`（zh-CN）、`/.../`（音标→跳过）切分为段落。逐段 `SpeechSynthesisUtterance` 播放。

### 12.2 播放层级

| 层级 | 触发方式 | 内容 |
|------|---------|------|
| L1 自动序列 | ▶ 按钮 | 按题型决定的模块序列 |
| L2 手动模块 | 每模块 🔊 按钮 | 单模块朗读 |
| L3 原文 | 📄 旁 🔊 按钮 | 全文朗读 |

### 12.3 按题型自动序列

| 题型 | 序列 |
|------|------|
| grammar_cloze / cloze | 解析 → 考点 → 上下文 |
| reading_comp | 解析 → 考点 → 题干定位 |
| true_false | 解析 → 考点 → 原句/题干 → 原文依据 |

### 12.4 约束

- 滑动/键盘翻页不触发自动朗读
- 生词洞察仅手动触发（逐词朗读，跳过音标）
- 选项词义、排除法不朗读（视觉对比任务）
- 缺失语音包时按钮禁用并提示

## 十三、管线可观测性（pipeline_log.py）

### 13.1 事件类型

| 事件 | 调用处 | 内容 |
|------|--------|------|
| upload | main.py | file_count, total_bytes |
| ocr_start | engine.py | method, image_path, image_bytes |
| ocr_result | engine.py | duration_ms, text_length, success |
| stage1_entry | engine.py | — |
| stage1_result | engine.py | q_count, exam_type, success/error |
| variant_detect | engine.py | variant, exam_type |
| llm_start | engine.py | ocr_text_length, model |
| llm_result | engine.py | duration_ms, output_length, success |
| retry | engine.py | stage, attempt, reason |
| trace | engine.py | 轻量调试标记 |

### 13.2 格式

JSON Lines → `data/pipeline.log`。每行 `{step, session_id, ts, ...}`。按 session_id 检索重建完整管线追踪。

## 十四、组件结构

```
exam-tutor/
├── agent/
│   ├── main.py          # FastAPI + SSE (单进程 :8080)
│   ├── engine.py         # process_exam()
│   ├── ocr.py            # tesseract CLI
│   ├── tools.py          # 6 个 Tool Definition + 路由表
│   ├── prompts.py        # System Prompts + User Prompt builders
│   ├── store.py          # SQLite CRUD
│   └── pipeline_log.py   # 管线日志
├── webui/
│   ├── index.html        # SPA（三屏幕 + TTS + 原文溯源）
│   ├── manifest.json
│   ├── sw.js
│   └── icons/
├── data/
│   ├── exams.db
│   └── pipeline.log
├── DESIGN.md
└── README.md
```

## 十五、Messages 协议

```
Stage 1:
  system:  "You are an exam text parser... Call parse_exam..."  (~150 tokens)
  user:    "OCR TEXT:\n{ocr_text}"                              (500–1500 tokens)
  extra:   thinking=disabled
  → assistant: tool_call → parse_exam(arguments)

Stage 2:
  system:  "You are an English exam tutor... Choose the function..."  (~200 tokens)
  user:    "Passage:\n{passage}\n\nQuestions:\n..."                    (500–2000 tokens)
  tools:   5 tool definitions (strict: true)
  tool_choice: "required"
  → assistant: tool_call → generate_{type}(arguments)
```

每个 Stage 是独立的消息对。Stage 2 LLM 从 5 个工具中自选——选择记录在 pipeline.log。
`tool_calls` 为空或 JSON 解析失败时自动重试（最多 2 次）。API 500 级错误同样重试。

## 十六、验收标准

| # | 标准 | 验证方法 |
|---|------|---------|
| 1 | 同一份试卷连续上传 3 次，均成功 | 端到端测试 |
| 2 | 每种题型输出模块数与 Tool Schema 一致 | Strict Mode 保证 |
| 3 | answer 值符合对应 enum 约束 | Strict Mode 保证 |
| 4 | 无多余字段 | Strict Mode `additionalProperties: false` 保证 |
| 5 | 多页试卷选项正确跨页映射 | 端到端测试 |
| 6 | 进程数 = 1 | `ps aux` |
| 7 | System Prompt ≤ 200 tokens / stage | tokenize 测量 |
| 8 | 模块内容格式符合 Tool description 规范 | 人工抽查 |
| 9 | 系统中不存在 validate.py、contracts.py、parser.py | 代码审查 |
| 10 | 前端三屏幕按 SSE 事件正确切换 | 端到端测试 |
| 11 | 模块默认展开/折叠行为正确 | 手动测试 |
| 12 | 移动端滑动、桌面端键盘翻页正常 | 手动测试 |
| 13 | PWA 离线可访问 | 断网后刷新 |
| 14 | SSE live 与历史路径渲染结果一致（含 passage 和原始文本） | 端到端测试 |
| 15 | 同一文件连续选择 3 次均触发上传 | 手动测试 |
| 16 | 「加载更多」在所有记录数下正确 | 边界验证 |
| 17 | SSE 网络微抖不弹框，3 次失败后弹框 | 模拟断网 |
| 18 | TTS 按题型使用正确模块序列 | 3 种题型抽查 |
| 19 | 缺失语音包时 TTS 按钮禁用并提示 | 模拟无语音浏览器 |
| 20 | `start.sh` 预检通过后才启动服务 | 错误配置 → exit 1 |
| 21 | `/health` 返回配置摘要和门禁状态 | `curl /health` |
| 22 | `/api/config` 返回前端需要的参数 | `curl /api/config` |
| 23 | 前端 onload 从 `/api/config` 获取动态常量 | 修改 config.yaml 后前端自动对齐 |

## 十七、配置系统（v5.1）

### 17.1 文件结构

```
exam-tutor/
├── config.yaml          ← 所有可配置参数的唯一事实源
├── .env.example         ← 环境变量模板（API Key）
├── .env                 ← 实际密钥（gitignore）
└── agent/
    └── config.py        ← 加载器 + 门禁 + 两级 LLM 覆盖
```

### 17.2 加载优先级

```
环境变量 > config.yaml > 代码默认值
```

`.env` 文件在门禁期自动加载（不覆盖已设环境变量）。

### 17.3 LLM 参数两级覆盖

```
llm:                          ← 全局（所有 Stage 继承）
  model: "deepseek-chat"
  base_url: ...
  retry_attempts: 2

  stage1:                     ← Stage 覆盖（仅温度）
    temperature: 0.0

  stage2:                     ← Stage 覆盖（多项）
    temperature: 0.3
    max_tokens: 16384
    truncation_batch_size: 2
```

`config.llm_for("stage1")` 返回合并后的扁平 dict。

### 17.4 门禁分层

| 层级 | 时机 | 检测项 | 失败结果 |
|:--:|------|------|------|
| 启动 | `uvicorn.run` 之前 | Schema 合规、API key 存在、路径可写、值域合法 | `exit(1)` + 中文错误 |
| 运行时 | 首 LLM 调用 | `base_url` 可达性、model 有效性 | SSE error 事件 |
| 健康 | 任意时刻 | `/health` 端点 | JSON status |

### 17.5 前后端协同

前端 onload 时 `fetch('/api/config')` 获取：

```json
{
  "upload_max_mb": 5,
  "allowed_types": ["image/jpeg","image/png","image/webp"],
  "page_size": 20,
  "api_base": ""
}
```

- `<input accept>` 动态拼接
- 分页大小动态注入
- API base URL 动态注入
- 图片预处理参数（MAX_SIDE/JPEG_QUALITY）保留为前端常量（UX 决策）

### 17.6 新增端点

| 端点 | 用途 |
|------|------|
| `GET /health` | 配置门禁状态、API key 存在性、路径可写性 |
| `GET /api/config` | 前端所需配置项（无密钥） |
