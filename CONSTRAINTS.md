# 系统架构约束

本文档定义三条跨模块的强制性约束。每一条都源于实际发现的系统性缺陷模式，而非抽象原则。

---

## 一、信任边界清单

系统的每个外部输入点必须在入口处显式校验。以下边界已全部覆盖或被标记为"已加固"。

| 边界 | 输入 | 校验 | 状态 |
|---|---|---|---|
| HTTP → 文件系统 | `img.filename` | `Path(name).name` 防穿越 | ✅ 已加固 |
| HTTP → 数据库 | `exam_id` / `page` / `search` | 参数化查询 + user_id 过滤 | ✅ |
| HTTP → LLM API | `body.password` | bcrypt + min length | ✅ |
| SSE → JS 运行时 | `e.data` | `try { JSON.parse } catch { return }` | ✅ 已加固 |
| 外部进程 → 管线 | tesseract stdout | 质量门（空/过短/英文占比） | ✅ |
| LLM API → 管线 | tool_call arguments | `_parse_json` 三层恢复 | ✅ |
| LLM API → 存储 | `finish_reason == "length"` | 分片重试 | ✅ |
| Config 文件 → 内存 | `config.yaml` | 全字段校验（URL/端口/路径/AKI key） | ✅ |
| 词汇提取 → 词汇表 | `extract_words()` | STOPWORDS 过滤（纯功能词） | ✅ 已加固 |
| IP → GeoIP 查询 | `request.client.host` | geoip2 → ipapi.co → 空 | ✅ |
| 前端 → 后端 | `POST /auth` body | 学号/姓名非空校验 | ✅ |

**规则**：新增输入点时，必须在此表中声明其校验策略。没有校验的边界 = 不允许合并。

---

## 二、资源生命周期所有权

每个资源（文件句柄、数据库连接、asyncio Task、mmap）必须在创建时绑定到明确的销毁路径。

| 资源类型 | 创建点 | 销毁路径 | 状态 |
|---|---|---|---|
| `sqlite3.connect()` | `ExamStore._connect()` | `with self._connect() as conn:` | ✅ |
| `geoip2.database.Reader` | `geoip.py:_query()` | `with ... as reader:` | ✅ 已加固 |
| `asyncio.create_task()` | `main.py:create_exam` | `add_done_callback(lambda t: t.exception() and log)` | ✅ 已加固 |
| `EventSource` | `useSSE.js:start()` | `es.close()` in cancel + cleanup effect | ✅ |
| `asyncio.Queue` | `main.py:sse_ui` | `queues.remove(q)` in finally | ✅ |
| `asyncio.Task` (heartbeat) | `engine.py:_run_pipeline` | `heartbeat_task.cancel()` in finally | ✅ |
| `AbortController` | `useSSE.js:start()` | `abort()` in cancel | ✅ |
| `ImageBitmap` | `HomeScreen.jsx:preprocess` | `bmp.close()` after use | ✅ |

**规则**：任何 `open()` / `connect()` / `create_task()` / `new EventSource()` 必须在同一函数内可见其对应的 `close()` / `cancel()` / `removeEventListener()`。如果不可见 → 设计缺陷。

---

## 三、信息编码准则

返回值必须编码所有可区分状态。禁止用单一值（如 `False` / `None` / `""`) 表示多种不同语义。

### 已修复

| 函数 | 修复前 | 修复后 |
|---|---|---|
| `_parse_json()` | `tuple[dict\|None, bool]`（bool 永远 False） | `dict \| None` |
| `toggle_star` endpoint | 不存在 → 200 `{starred: false}` | 不存在 → 404 |
| `StudentDB.create()` | 忽略传入 `id`，自生成 UUID | 使用传入 `id`，fallback 随机 |

### 已知但可接受

| 函数 | 多义返回 | 理由 |
|---|---|---|
| `toggle_star()` store 方法 | 不存在和取消收藏都返回 `False` | 调用方通过额外 `get_exam` 区分。内部方法，影响可控 |

**规则**：新增函数时，其返回值类型必须在 docstring 中声明，且所有调用方必须处理每种可能状态。`bool` 返回值的函数必须回答："`False` 代表什么？调用方如何知道？"

---

## 变更历史

| 日期 | 变更 |
|---|---|
| 2026-06-15 | 初始版本。源于 v6.1 代码质量评审中识别的 3 条系统性模式 |
