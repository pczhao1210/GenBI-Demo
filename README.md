# GenBI - 生成式 BI 查询系统

使用自然语言查询 MySQL / AWS Athena / PostgreSQL / Microsoft SQL Server，并生成基于查询证据的多步骤分析报告。

## 当前能力

- Streamlit 配置与聊天界面，中文 / English 切换。
- OpenAI、Azure OpenAI、OpenAI SDK 和自定义 HTTP LLM。
- 数据源 ID、多连接、四类数据库适配与驱动诊断；Schema 编辑、批量描述、业务键及预览。
- 单条只读 SQL 校验，支持 `SELECT`、CTE、聚合、关联和集合查询。
- 持久任务、真实事件进度、澄清、计划确认/修改、协作式取消、恢复、局部重试与回放。
- 查询结果、分析报告和错误保留在当前会话；切换数据源不会混用计划。
- 前端与 FastAPI 复用同一业务服务，不返回模拟查询或连接成功。
- Ontology、知识/方法检索、多轮槽位与业务日解析、按节点职责的模型路由。
- 有界证据评估与重规划、跨源确定性关联/比率计算、外部来源及事实追踪。
- 结论卡、表格/图表、完整运行 JSON/表格 CSV 导出，以及无需连接的显式样例回放。
- 内置按需 stdio 工具与独立标准 MCP stdio / Streamable HTTP 适配。

## 安装与启动

推荐 Python 3.12。锁文件为 Python 3.12 生成，CI 使用相同依赖。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
./start.sh
```

启动脚本不会每次重新安装依赖。它在两个服务健康检查通过后报告就绪，
任一服务退出或收到 Ctrl+C 时清理本次启动的服务。
仓库内 Streamlit 配置启用了非交互启动，并关闭使用统计上报。

- 前端：http://localhost:8501
- API 文档：http://localhost:8000/docs
- API 健康检查：http://localhost:8000/health

手动启动时，在**仓库根目录**使用两个终端：

```bash
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

`./start.sh --language=English` 可选择英文。可通过
`GENBI_BACKEND_PORT` / `GENBI_FRONTEND_PORT` 指定端口；非默认后端端口需在 API 文档页面同步修改 API Base URL。

### 网页搜索的可选准备

Python 依赖已包含 Playwright，但浏览器需要额外安装：

```bash
.venv/bin/python -m playwright install chromium
```

Linux 上还可能需要浏览器系统库，参见 Playwright 安装提示。
未安装浏览器、网络不可达或没有搜索结果时，外部数据步骤会失败，并跳过依赖步骤；
**不会替换为虚构的天气、市场或行业数据**。

## 推荐使用流程

1. **LLM 配置**：填写模型和连接参数，测试并保存。自定义 OpenAI 兼容地址可填写
   `/v1` 基础地址或完整 `/v1/chat/completions` 地址。
2. **数据库配置**：配置 MySQL 或 Athena，实际测试连接后保存。
   Athena 支持 Region、Database、Catalog、Workgroup、S3 输出位置和临时会话凭据。
   凭据留空使用 AWS 默认凭据链。
3. **工具管理**：确认对应内置服务器已启用按需调用。首次初始化默认启用内置工具；
   旧配置中已禁用的服务器需要手动启用。
4. **Schema 配置**：刷新表列表、获取字段、编辑描述并保存。
   清空操作会持久清空**当前数据源 ID** 的 Schema，不影响其他连接。
5. **聊天**：查询直接执行；复杂分析先展示计划，再点击执行或输入修改意见。
   计划绑定当前连接和 Schema；失败或被跳过的步骤不会显示为完成。

配置按稳定 `datasource_id` 保存多连接与 Schema。首次使用自动将旧 MySQL/Athena
迁移为 `legacy-mysql` / `legacy-athena`，保存显式迁移映射，可重复执行且不按名称猜归属。
旧 API 的引擎参数仅在该类型恰有一个连接时解析；多个连接时必须指定 ID。
修改连接后应重新获取并保存对应 Schema。配置文件使用仓库绝对路径、原子替换和
读改写锁，不依赖启动时的工作目录。

## API

所有业务接口均使用真实业务逻辑。配置缺失或输入无效返回 400 / 422，
LLM、数据库或工具执行失败返回 502，不返回成功形状的模拟响应。

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/chat/generate-sql` | 生成并验证只读 SQL |
| POST | `/api/chat/query` | 生成 SQL 并执行查询 |
| POST | `/api/chat/analyze` | 生成分析计划 |
| POST | `/api/chat/optimize-chain` | 根据原计划和反馈修改计划 |
| POST | `/api/chat/execute-plan` | 执行计划，返回每步状态与数据 |
| GET | `/api/database/schema?db=mysql` | 读取已保存 Schema |
| POST | `/api/database/test-connection` | 实际测试数据库连接 |
| POST | `/api/llm/test-connection` | 实际调用 LLM 测试连接 |
| GET | `/api/llm/models?provider=openai` | 从提供商获取模型列表 |
| POST | `/api/llm/chat` | 保留完整消息历史的 LLM 对话 |
| POST | `/api/mcp/execute` | 执行内置注册工具 |
| GET | `/api/mcp/status` | 检查配置启用状态及脚本响应能力 |

```bash
curl -X POST http://localhost:8000/api/chat/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"显示前10行数据","database":"mysql"}'
```

计划中 `dependencies` 和 `analysis_requirements.input_data` 使用整数步骤 ID。
执行器按依赖顺序运行，依赖失败时返回 `skipped`。部分失败的计划返回
`status: "partial"`、`completed: false`，而不是把整个计划标记为成功。

## 结果与运行边界

- 始终使用数据库只读账号 / 最小权限 IAM；SQL 解析校验不能替代数据库权限。
- MySQL 在 SQL 和读取阶段限制返回行数；Decimal 以字符串返回以保留精度。
- Athena 分页读取结果，保留 NULL；达到上限返回截断标记。
- Athena 查询达到超时会请求取消；结果下载超时不会返回假完整的部分结果。
- 工具调用有进程超时；脚本探测成功只代表能响应，不代表数据库连接成功。
- 聊天通过持久任务服务执行；运行、事件、输入快照和结果保存在 `data/runs.sqlite3`。
  终态重试创建关联运行，成功且配置未变的步骤可复用；刷新不复用。回放不调用外部服务。
  中断恢复需确认原执行进程已退出；无法确认完成的在途调用可能重执行，不承诺 exactly-once。
  取消为协作式：立即停止后续调度，在途调用结束后才进入 `CANCELLED`。
- 当前工具是内置换行 JSON RPC 兼容层，**不是完整 MCP 2025 协议实现**，
  标准 MCP 另有 stdio / Streamable HTTP 适配器，不支持 SSE。详见[工具说明](mcp_servers/README.md)。
- 默认只监听本机；当前没有多用户认证或租户隔离，不应直接公开到互联网。
- 收藏、轻量看板和持续性能指标尚未实现；调用记录不是完整监控平台。

### 持久任务 API（P0）

`POST /api/runs` 接收 `question`、`database`、`session_id`（可选）、
`submission_id`（调用方生成的幂等键）和可选的固定 `plan`。
`GET /api/runs/{run_id}` 返回生命周期、阶段、计划版本和逐步状态；
`GET /api/runs/{run_id}/events?after=0` 按递增游标读取最多 500 条事件。
结果通过 `/artifacts/{artifact_id}` 读取，不在状态中重复保存大表。

`POST /responses` 用 `request_id`、`plan_version`、`response` 恢复澄清或确认；
计划确认回复为 `confirm`。`POST /plan` 在确认点显式提交新计划及匹配的请求/版本。
`POST /cancel`、`POST /resume`、`POST /retry?refresh=false` 分别取消、恢复和创建关联重试。
上述路径均以 `/api/runs/{run_id}` 为前缀。等待用户不计入活动时长。
固定 DAG 支持并行分支、必要依赖阻塞，以及显式允许缺失输入的可选依赖。
执行全失败为 `FAILED`，有可用结果且部分失败为 `PARTIAL`。

## 开发与验证

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q app.py backend pages utils mcp_servers
bash -n start.sh
```

测试覆盖配置读写、SQL、LLM、数据库结果处理、API 和 Streamlit 页面状态。
数据库、LLM 和搜索用替身验证；stdio 脚本探测使用真实子进程，不连接外部服务。

修改依赖后可使用 `uv` 重新生成锁文件：

```bash
uv pip compile requirements-dev.txt --python-version 3.12 --universal --output-file requirements.lock
```

核心文件：[共享业务服务](utils/bi_service.py)、[配置管理](utils/config_manager.py)、
[LLM 客户端](utils/llm_client.py)、[SQL 校验](utils/sql_utils.py)。
原始[项目规划](GenBI_Project_Plan.md)仅作为路线参考，不代表所有功能已实现。

### 多数据源（P1）

在数据源页按类型新增命名连接，测试实际连接，保存后在 Schema 页选择对应 ID。
`GET/POST /api/database/sources` 管理目录；
`GET /api/database/sources/{id}/metadata?table=...` 和 `/preview?table=...` 获取元数据和有限预览。
同步查询可用 `datasource_id` 指定连接，任务的 `database` 也接受稳定 ID。
引擎别名 `pgsql` / `postgres` 规范化为 `postgresql`。新驱动使用 SQLAlchemy 2.x、
psycopg 3 和 pyodbc；旧 MySQL/Athena 继续使用现有工具。

MSSQL 需在宿主机安装 **unixODBC 和 Microsoft ODBC Driver 18 for SQL Server**。
仅安装 Python 依赖不足；数据源页“能力与驱动诊断”会检查驱动是否存在。
按操作系统使用 Microsoft 官方安装说明：https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server
连接失败、驱动缺失与 SQL 错误均显式报告。统一结果记录源 ID、采集时间、类型、时区、
完整性与警告；Decimal 保留字符串精度，日期为 ISO，NULL 为 null。

验证边界：离线测试覆盖四类方言、多连接隔离、迁移、预览及结果类型；尚未使用真实
PostgreSQL/MSSQL 服务验收连接、元数据与查询，也未在本机安装 Microsoft 系统 ODBC 驱动。

### 语义、多轮与模型角色（P2）

“业务语义与知识”页维护结构化 Ontology 和 UTF-8 知识文档。指标需明确公式、聚合、
时间字段、单位、允许维度和数据源映射；保存时校验表字段与 ID，未映射指标只可解释。
轻量检索使用持久化文档和启动时构建的中英词项索引，返回片段位置、来源、版本与适用范围；
不要求向量服务。术语解释无需连接数据库。

任务先由快速模型输出 NER 槽位补丁，代码校验原文位置、实体 ID、维度兼容性与时间区间。
追问仅继承同一会话/数据源的成功上下文；相对日按本轮创建时间、业务时区和业务日计算，
恢复复用冻结输入。歧义通过带请求 ID 的澄清恢复，不在确认前取数。
模型页可覆盖 `fast` / `sql` / `reasoning` 的完整连接配置；未覆盖角色共用主模型。
调用记录包含角色、实际模型、耗时、状态与调用次数；当前客户端未提供 token 计数时记为 null。
模型错误显式失败，不自动降级。

`GET/PUT /api/semantics/ontology`、`GET/PUT /api/semantics/knowledge` 管理内容，
`GET /api/semantics/search?q=...&scope=...` 可试验检索。真实 NER/LLM 语义准确率仍需联调评测，
离线夹具仅验证槽位、时间、结构、路由与恢复合同。

### 有界分析与方法复用（P3）

方法库和验证案例在语义页维护，经过 draft → validated → published → deprecated；
发布需要人工审核记录和回归夹具 ID。检索同时检查工具与数据前提，仅将可迁移指令交给
强模型重新绑定，不传递历史 SQL、源 ID 或结论。无适用方法时仍可通用规划。

复杂任务确认后执行“DAG → 证据评估 → 必要重规划”，持久化目标、假设、缺口、
新证据与停滞计数。默认最多 30 步、64 次步骤调用、32 次模型调用、300 秒活动时长、
2 次重规划或连续 2 轮无新增证据；暂时性超时/连接错误最多重试 2 次。
SQL 字段/语法错误最多修正 2 次，第二次升级 reasoning；合法空结果不当作语法错误重试。
输入或步骤变化时仅失效受影响后代，仍有效分支不重取数。

强模型先输出可校验结论包，数值必须精确绑定到结果单元格、引用必须存在；
前提不成立时停止归因。快速表达只安排不可变结论的顺序，数字、文字和引用由代码渲染，
不能新增事实。`SUCCEEDED + INSUFFICIENT` 表示调查完成但证据不足，不表示找到根因。
当前方法验证记录由人工提供，未自动训练模型；真实新领域泛化效果仍需独立留出集评估。

### 跨源计算与外部证据（P4）

聊天侧栏选择活动数据源集合，任务 API 接收 `datasource_ids`。每个 SQL 步骤独立绑定
`datasource_id`，运行冻结源配置与 Schema；计划引用集合之外的源会明确失败。
步骤类型新增 `compute` / `data_align` / `knowledge_retrieval`，旧计划与同步 API 仍可用。

跨源优先源端聚合，本地用 Pandas 执行有限计算，不支持任意联邦 SQL。
`compute_requirements` 声明 `inputs`、`operation` 与列参数；支持 join、aggregate、
ratio、difference。Join 必须明确键与基数，双方需声明相同实体、粒度、时间区间、
时区及兼容单位；SQL 步骤用获确认的 `result_contract` 声明语义假设，代码检查实际键、
唯一性、未匹配比例及汇总值，不能仅凭列名相同推断业务实体相同。
多对多拒绝执行，一对多重复度量不允许直接汇总。比率先汇总分子分母再除，NULL 默认拒绝，
零分母保留 NULL。输入/输出上限为 10,000 行、16 MiB，关联前估算膨胀；不静默截断。
Decimal 计算精度显式为 50 位；保留各源采集时间，不假设跨库一致性快照。

外部步骤可以先搜索再抓正文，也可直接获取 HTTP(S) 文档/结构化 API，或按能力调用
标准 MCP 工具。搜索摘要仅为 discovery，不允许当作结论证据。
`evidence_need` 明确 variable、region、unit、绝对 start/end；
文本抽取校验原文位置及各值，结构化 API 可用 `field_mapping` 声明 records_path、
value/unit/region/observed_at/variable 字段，保留 JSON Pointer。时间、地区、单位不匹配的
事实排除并记录警告；无匹配事实为证据不足。发布时点与观测时点分别保留，未知不补造。
实际模型/工具调用均计入独立预算，外部抓取有超时和 2 MiB 文档预算。

本地标准 MCP stdio fixture 已验证真实协议协商、发现、调用与错误，Streamable HTTP 也有
本地服务协议测试；远程第三方 MCP、真实搜索/第三方 API 仍未联调。

### 演示闭环（P5）

首页按模型 → 数据源 → Schema → 最小语义映射提供配置向导、直接跳转和最近任务。
导航分工作区、配置与知识、开发入口；中英文切换不改变运行输入。
聊天侧栏仅保留会话历史和活动源；新问题创建独立任务，计划修改使用独立按钮。
结果优先呈现结论与关键数值，表格可切换经字段/唯一性/数值校验的趋势、分类或占比图；
图表只近似展示，JSON/表格保留 Decimal 精度。口径、覆盖、来源、SQL 和调试信息逐层展开。
Schema 页支持字段检索、批量描述/业务键、刷新字段差异和有限行预览。

历史任务与样例均显示记录时间、非实时标识；回放只读，不产生外部调用。
刷新明确创建新运行并重新取数，重试保留原先冻结的绝对时间和分析合同。
演示场景包含先决条件、初始问题和推荐追问，保存在
[示例场景](config/example_scenarios.json)，不固化为核心业务流程。

`GET /api/runs/{id}/replay` 返回完整历史事件与结果；
`GET /api/runs/{id}/export?format=json|markdown|csv&artifact_id=...` 导出 JSON、报告或指定表格。
CSV 的 NULL 表示为空字段；完整类型、单位、完整性和证据请使用 JSON。
计划修改可用 `POST /api/runs/{id}/plan/feedback` 提交 request_id、plan_version 和 feedback。

### 本轮验证状态

| 验证类型 | 状态 |
|---|---|
| 状态/事件/恢复、幂等、取消、并行合并、局部重试与预算 | 固定替身回归 |
| 多源迁移、SQL 方言、Decimal/NULL、关联基数、比率与超限 | 确定性离线夹具 |
| NER 槽位、相对日期、语义约束、角色路由、事实绑定 | 离线结构/语义合同测试；非真实模型准确率 |
| 标准 MCP stdio 发现/调用/错误与 Streamable HTTP 调用 | 本地真实 SDK/子进程/HTTP 协议测试 |
| Streamlit 页面、语言、样例、回放/导出 | AppTest 与浏览器检查 |
| 实际数据库、模型效果、远程 MCP/搜索/外部 API、方法泛化 | 尚未完成真实环境验收，不作完成或性能承诺 |

本轮保留显式 Python 工作流，不引入分布式调度或多 Agent 群聊。
所有六阶段均有代码增量，但数据库/模型联调及独立领域评测仍是后续验收工作。

## 许可证

[MIT License](LICENSE)。
