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
2. **数据库配置**：配置 MySQL、Athena、PostgreSQL 或 MSSQL，实际测试连接后保存。
   Athena 支持 Region、Database、Catalog、Workgroup、S3 输出位置和临时会话凭据。
   凭据留空使用 AWS 默认凭据链。
3. **工具管理**：确认对应内置服务器已启用按需调用。首次初始化默认启用内置工具；
   旧配置中已禁用的服务器需要手动启用。
4. **Schema 配置**：刷新表列表、获取字段、编辑描述并保存。
   清空操作会持久清空**当前数据源 ID** 的 Schema，不影响其他连接。
5. **聊天**：查询直接执行；复杂分析先展示计划，再点击执行或输入修改意见。
   计划绑定当前连接和 Schema；失败或被跳过的步骤不会显示为完成。

### 配置界面：业务 Profile、知识与节点模型

共享业务可先保存连接与表结构，再定义 KPI/知识、创建 Profile。私有业务可先创建草稿 Profile，
在全局侧栏选中它，再创建仅该 Profile 可见的资源，最后勾选资源并取消草稿状态。
首页保留各配置入口和状态；“已配置”不代表真实连接测试通过。

**业务 Profile**

在「业务 Profile」新增业务方向（例如“销售分析”），选择多个连接，并为每个连接明确勾选多张表；
再选择可用 MCP/内置 RPC、知识文档、查询知识和分析方法。知识文档按“知识库 / 标题”展示。
空工具、知识、方法列表表示不使用这些资源；新添加的表/文档不会自动进入已有 Profile。
MySQL/Athena 数据库自身的传输适配器自动保留，其他内置计算能力仍然可用。
选择 MCP 不等于启用，仍需在工具页发现和逐工具启用。

全局侧栏选择 Profile，在聊天选择主数据源后，Profile 中所有连接共同组成活动范围。
规划只能看到所选 Schema，SQL 执行前还会检查物理表（包括 CTE、子查询、关联与限定名称）；
元数据也只返回所选表。跨源查询依旧按步骤绑定数据源，不向单库提交跨源 SQL。
物理映射完全位于范围外的业务定义不会传入运行；无预设映射的定义由模型匹配范围内 Schema，有歧义先澄清。
Profile 是业务范围，不是数据库权限或多租户安全边界；第三方 MCP 自身的数据权限仍由服务端控制。
如果全局默认工具提供方不在 Profile 中，会明确报错，不自动改用其他提供方。

不同 Profile 的会话相互隔离。配置按运行冻结，修改只影响新任务；重试/刷新保留 Profile 身份，
按当前配置重新检查，已删除的 Profile 不会悄悄变成无限定模式。
未选择 Profile 时，新任务只使用共享资源；旧配置未声明范围的普通资源视为共享，历史任务快照不改写。

**共享与私有、编辑与删除**

- 连接、业务定义、文档、查询知识、方法/案例均可选择「共享」或「仅当前 Profile」。
- 表定义、字段 Schema 和说明共用一个表级范围，并受所属连接范围限制；不单独划分每列权限。
- 共享是**可发现、可复用**，不是自动授权。Profile 仍需明确选择连接、表、文档、查询知识和方法。
- 切换 Profile 会清空未保存草稿；保存时合并其他 Profile 的隐藏记录，不会将它们覆盖或清空。
- 在「编辑已有 / 新增」选择保存的条目即可修改；稳定 ID 不变。删除需确认，被引用资源需先解除引用。
- Schema 可直接编辑已保存表，也可离线手工创建表定义、增删字段、修改名称/类型/说明。
  应用只修改配置，**不会创建、修改或删除真实数据库表**。请自行核对实际结构。

**业务知识中心：一个目录、三种录入模板**

页面左侧按名称/内容、类型和共享范围筛选知识，右侧编辑所选条目。原来的六个 Tab 合并成一个目录；
指标、文档、指南、已有方法和案例都可以直接找到。新增时只选择以下三种模板：

| 录入模板 | 配置内容 | 示例 / 生效条件 |
|---|---|---|
| 指标 / 业务定义 | 指标名称、业务定义；统计对象和分析维度可选 | 每个输入框直接给示例，也可一键载入四字段草稿 |
| 查询 / 分析指南 | 典型问题或指南名称、推荐处理方式 | 可关联业务定义、连接/表、文档和方法，并在同一表单维护适用问法和业务示例 |
| 参考资料 | 标题、正文或 TXT/Markdown 文件 | 来源、主题和版本可选；运行只检索当前 Profile 选中的文档 |

指标四字段示例：**净销售额**；**逐订单行计算单价×数量×折扣并扣除退款后汇总**；
**统计各公司，基础粒度为订单明细，同名公司不混同**；**可按月份、地区或产品分析**。
“分析维度”是业务说明，不会自动变成硬性白名单。只有高级设置勾选严格维度限制时，
`allowed_dimensions` 才作为约束；此时空列表仍表示不允许任何维度。
公共统计对象和维度可通过高级模板单独维护，再由指标引用，无需重复复制。

稳定 ID 留空会自动生成，重命名不改变 ID 或 Profile/指南引用；公式、聚合方式、单位、时间字段和物理映射均可选。
不会自动把聚合方式设为 `sum`，也不要求重复填写业务定义里已经表达的公式。
原有仅含定义、没有显示名称的记录继续可用，先以原 ID 显示；不自动迁移、改名或改写历史快照。
没有预设映射时，理解节点结合当前 Profile 的已保存 Schema 判断口径，SQL / 规划节点匹配实际字段。
组件含义、字段、粒度或汇总方式有歧义时先确认，不猜业务规则；多个活动连接走规划流程。
显式填写的映射和维度限制仍生效，生成的 SQL 仍经过只读与 Profile 表范围检查。
缺少 Schema 不能凭定义编造数据。直接 `/api/chat/query`、`/api/chat/generate-sql` 遇到歧义返回明确错误；
需要多轮确认或跨源规划时使用聊天或分析接口。
知识来源留空时标记真实的手工录入 / 上传文件名，版本默认为 1，主题默认为通用。
“载入示例”只替换编辑草稿，不自动保存；保存仍校验当前数据源及发布要求。
普通表单也提供编写说明和示例，不再只在高级 JSON 中展示。

四种概念可以这样区分：**KPI** 是算什么（净销售额）；**实体** 是业务对象（公司，A 公司是实例）；
**维度** 是按什么筛选/分组（公司、月份、地区）；**方法** 是按什么步骤调查（确认口径→对比期间→按地区拆分）。
同一“公司”可以既是实体又是分组维度，但维度没有步骤顺序。

例如创建指南“查询 A 公司本月净销售额”，处理方式写“确认公司唯一 ID 和日期，
按净销售额口径汇总订单行；同名公司先澄清”，再关联公司实体、净销售额 KPI、订单表和口径文档。
Profile 选用该知识时必须同时选中它依赖的资源，不会自动扩大范围。检索最多匹配 3 条，
每条可带最多 4 个关联文档片段，并优先推荐符合前提且已发布的方法。
示例公司和日期必须重新绑定当前问题；这不是旧 SQL、旧答案或历史数值回放。
每个指南可维护最多 8 条“示例问题 + 处理方式”，示例继承指南范围并参与匹配。
业务示例在知识中心管理，节点的 JSON/SQL 输出格式示例仍在「模型与 Prompt」，不混为一类。

这里的“思维链”以**公开、可审阅的分析步骤**呈现，不是模型隐藏推理。
需要可执行 DAG 时，通过指南的高级模板创建方法；保存指南后可直接打开关联方法管理步骤与案例。
普通知识不新增强制评审字段；方法/案例保留原有草稿、验证和发布机制。
发布方法需要填写实际评审人、通过的测试用例编号及验证记录；勾选验证通过不会替你运行测试。
复杂计算节点可在条目高级 JSON 配置完整参数，普通查询/分析步骤直接在表格中编辑。
批量 JSON 编辑/导入导出下沉到页面底部，并保留可复制、载入草稿的示例。

**按工作流阶段使用知识**

默认自动分配使用位置：理解/澄清、规划/重规划、SQL 生成/修复、结果分析、术语解释；
高级用户可调整条目的 `retrieval_stages`。指南和文档统一由阶段上下文组织，方法仍检查发布状态与前提。
理解、规划和 SQL 阶段始终保留范围内的业务定义/约束，不能因未命中检索或关闭自动检索而绕过。
口径文档和指南不是当前数值证据；结果表达只使用已经验证的结论，不额外检索生成新事实。
显式知识查询工具仍按其资源范围工作，阶段设置不作为资源权限。
知识及阶段配置随运行冻结，知识变化会使相关 SQL/分析步骤的复用失效。

页面底部提供**检索试用**：输入问题并选择阶段，显示匹配知识、固定业务约束、
未纳入 Profile 执行范围的条目和缺少的关联资源。试用使用真实范围过滤，不调用 LLM、不执行 SQL。

**模型与 Prompt**

分为「全局默认模型」「模型角色」「工作流节点与 Prompt」三个标签。
有效优先级为 **节点独立模型 > 角色独立模型 > 全局默认模型**，所有角色默认可以共用一个模型。
先填写全局服务地址和 API Key，点击**保存连接并刷新可用模型**。
随后默认型号、三个角色和节点型号均从下拉菜单选择，不需要重复填写连接。
角色/节点只保存 `model_name` 引用，运行时复用全局连接并冻结到任务快照。
模型列表按连接指纹持久保存，不保存凭据副本；更换地址或凭据后需要重新刷新。
刷新失败不编造列表、不替换旧连接；提供商不支持列模型时会明确报错。
已保存但未发现的型号会标为未验证，不自动换成另一型号；旧独立连接在明确重新选择前保留。
模型发现不保证所有型号均具有推理调用权限；仍可单独测试默认模型的实际调用。

| 默认角色 | 节点 |
|---|---|
| fast | 问题理解、兼容意图分类、外部事实提取、知识解释、结果表达 |
| sql | SQL 生成、首次 SQL 修复 |
| reasoning | 升级 SQL 修复、规划、计划修改、步骤分析、证据评估 |

每个节点先加载真实默认 Prompt，可直接编辑保存，或恢复默认后再保存。
默认指令统一维护在 [prompts.py](utils/prompts.py)，不会再同时隐藏一套相互冲突的静态指令。
问题、Schema 和证据动态注入，不需要编辑占位符；资源限制、只读 SQL 和结构化结果校验由程序保留。
One-shot / Few-shot 区以“示例输入 / 期望输出”表格编辑，并可载入各节点的示例格式：

- Zero-shot：不注入示例。
- One-shot：私有示例优先，再选共享示例，只注入第一条。
- Few-shot：同样先私有后共享，合计最多 8 条；表单至少填写 2 条适用示例。
- 创建时选择当前 Profile 或共享示例组。旧的无 Profile 示例仍仅用于兼容模式，不自动转成共享。
- 示例只说明响应方式，不是当前证据，不允许扩展 Profile 的连接、表、工具或知识范围。

资源绑定、用户确认、工具执行、确定性计算、取消/恢复和持久化由代码执行，无需 LLM。
聊天运行详情展示节点、型号和配置来源；运行记录包含 Prompt/示例版本指纹和实际示例数量。
模型与基础 Prompt 全局管理，示例支持共享或 Profile 私有。配置和默认 Prompt 均随新任务冻结。

**工具**

右侧主内容使用「内置工具」「MCP 扩展」**选项卡**，各自按类别展示。
内置区明确展示 MySQL、Athena、PostgreSQL (PGSQL)、Microsoft SQL Server (MSSQL) 四类连接器，
支持跳转到对应引擎配置和本机驱动诊断。PGSQL/MSSQL 是原生 SQLAlchemy 适配器，无需添加 MCP；
MSSQL 仍需要本机 unixODBC 和 Microsoft ODBC 驱动。

MCP 填写连接后，确认允许执行第三方软件，即可**一键验证连接并获取工具**。
成功后连接可用，但所有新发现工具默认关闭；逐工具开关立即持久化，并影响后续调用。
失败保留禁用配置并明确显示错误，不伪装成连接成功。也可仅保存禁用配置，稍后探测。
没有手动标准能力映射的工具自动使用 `mcp.<server>.<tool>`，无需猜测或填写能力名。
缺少只读声明的工具需要在工具策略中确认只读后才能业务调用。
技术 Schema、连接高级参数与调试详情按需展开。
内置能力随应用提供，不支持在界面上传任意代码增加内置工具；新增外部能力请使用 MCP。

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
| GET | `/api/mcp/status` | 读取启用状态与已有探测快照，不自动启动服务器 |
| POST | `/api/tools/servers/{server_id}/connect` | 保存新连接、验证和发现工具；`confirmed: true` 必须显式提供，工具默认关闭 |

```bash
curl -X POST http://localhost:8000/api/chat/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"显示前10行数据","database":"mysql"}'
```

计划中 `dependencies` 和 `analysis_requirements.input_data` 使用整数步骤 ID。
执行器按依赖顺序运行，依赖失败时返回 `skipped`。部分失败的计划返回
`status: "partial"`、`completed: false`，而不是把整个计划标记为成功。
同步兼容响应另有 `execution_status`，使用与持久任务一致的 `SUCCEEDED` / `PARTIAL` /
`FAILED` / `CANCELLED`；旧 `partial` / `skipped` 名称只在兼容边界映射。

## 结果与运行边界

- 始终使用数据库只读账号 / 最小权限 IAM；SQL 解析校验不能替代数据库权限。
- MySQL 在 SQL 和读取阶段限制返回行数；Decimal 以字符串返回以保留精度。
- Athena 分页读取结果，保留 NULL；达到上限返回截断标记。
- Athena 查询达到超时会请求取消；结果下载超时不会返回假完整的部分结果。
- 工具调用有进程超时；脚本探测成功只代表能响应，不代表数据库连接成功。
- 聊天通过持久任务服务执行；运行、事件、输入快照和结果保存在 `data/runs.sqlite3`。
  终态重试创建关联运行，成功且配置未变的步骤可复用；刷新不复用。回放不调用外部服务。
  复用还要求必要和可选依赖均保持有效；重试上游时，其下游结果一并失效。
  中断恢复需确认原执行进程已退出；无法确认完成的在途调用可能重执行，不承诺 exactly-once。
  取消为协作式：立即停止后续调度，在途调用结束后才进入 `CANCELLED`。
- 当前工具是内置换行 JSON RPC 兼容层，**不是完整 MCP 2025 协议实现**，
  标准 MCP 另有 stdio / Streamable HTTP 适配器，不支持 SSE。详见[工具说明](mcp_servers/README.md)。
- 默认只监听本机；当前没有多用户认证或租户隔离，不应直接公开到互联网。
- 收藏、轻量看板和持续性能指标尚未实现；调用记录不是完整监控平台。

### 持久任务 API（P0）

`POST /api/runs` 接收 `question`、`database`、`session_id`（可选）、
`submission_id`（调用方生成的幂等键）和可选的固定 `plan`。
可传 `profile_id`；省略 `datasource_ids` 时使用该 Profile 全部连接，`database` 仍需属于 Profile。
`GET /api/profiles`、`PUT /api/profiles/{profile_id}`、`DELETE /api/profiles/{profile_id}`
与 UI 共用资源校验。同步 `/api/chat/*` 同样支持可选 `profile_id`。
`GET /api/runs/history?profile_id=...` 可过滤 Profile；空字符串只选择未使用 Profile 的历史。
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
UUID、TIME 和 INTERVAL 结果分别保留为 UUID 字符串、ISO 时间和时长字符串，
数组中的原生值也会递归规范化，保证查询结果可以持久化和回放。

验证边界：离线测试覆盖四类方言、多连接隔离、迁移、预览及结果类型；尚未使用真实
PostgreSQL/MSSQL 服务验收连接、元数据与查询，也未在本机安装 Microsoft 系统 ODBC 驱动。

### 语义、多轮与模型角色（P2）

“业务知识中心”维护 Ontology、UTF-8 知识文档与查询/分析指南。指标表单填写名称与定义，
旧的仅定义 JSON 继续兼容；
公式、聚合、时间字段、单位、维度和物理映射可选；明确填写的映射仍校验表字段与 ID。
轻量检索使用持久化文档和按内容快照缓存的中英词项索引，返回片段位置、来源、版本与适用范围；
不要求向量服务。术语解释无需连接数据库。

任务先由快速模型输出 NER 槽位补丁，代码校验原文位置、实体 ID、维度兼容性与时间区间。
追问仅继承同一会话/数据源的成功上下文；相对日按本轮创建时间、业务时区和业务日计算，
恢复复用冻结输入。歧义通过带请求 ID 的澄清恢复，不在确认前取数。
模型页可覆盖 `fast` / `sql` / `reasoning` 的完整连接配置；未覆盖角色共用主模型。
调用记录包含角色、实际模型、耗时、状态与调用次数；当前客户端未提供 token 计数时记为 null。
模型错误显式失败，不自动降级。
模型网络超时和连接中断在角色路由层最多重试两次，每次尝试单独记录并计入模型预算；
达到活动时长预算后不再发起下一次尝试，步骤层不叠加模型网络重试。

`GET/PUT /api/semantics/ontology`、`GET/PUT /api/semantics/knowledge`、
`GET/PUT /api/semantics/methods`、`GET/PUT /api/semantics/queries` 管理内容；
`GET /api/semantics/search?q=...&scope=...` 可试验检索。
`GET /api/semantics/catalog` 返回统一目录元数据；
`GET /api/semantics/preview?q=...&stage=planning` 返回阶段检索上下文、固定约束和缺少的关联资源。
这些接口及数据库资源/元数据/预览接口支持可选 `profile_id`，省略时仅管理共享内容；
写入会保留当前范围外的记录。`DELETE /api/database/sources/{source_id}` 只删除连接配置，并检查引用。
真实 NER/LLM 语义准确率仍需联调评测，
离线夹具仅验证槽位、时间、结构、路由与恢复合同。

### 有界分析与方法复用（P3）

方法库和验证案例在语义页维护，经过 draft → validated → published → deprecated；
发布需要人工审核记录和回归夹具 ID。检索同时检查工具与数据前提，仅将可迁移指令交给
强模型重新绑定，不传递历史 SQL、源 ID 或结论。无适用方法时仍可通用规划。

复杂任务确认后执行“DAG → 证据评估 → 必要重规划”，持久化目标、假设、缺口、
新证据与停滞计数。默认最多 30 步、64 次实际工具尝试、32 次模型调用、300 秒活动时长、
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
指标可计算性按活动数据源集合检查；需要主数据源之外指标的查询先生成并确认计划，
不强行在主数据源执行。用户澄清回答作为显式依赖输入传入 SQL 生成。
步骤类型新增 `compute` / `data_align` / `knowledge_retrieval`，旧计划与同步 API 仍可用。

跨源优先源端聚合，本地用 Pandas 执行有限计算，不支持任意联邦 SQL。
`compute_requirements` 声明 `inputs`、`operation` 与列参数；支持 join、aggregate、
ratio、difference。Join 必须明确键与基数，双方需声明相同实体、粒度、时间区间、
时区及兼容单位；SQL 步骤用获确认的 `result_contract` 声明语义假设，代码检查实际键、
唯一性、未匹配比例及汇总值，不能仅凭列名相同推断业务实体相同。
多对多拒绝执行，一对多重复度量不允许直接汇总。比率先汇总分子分母再除，NULL 默认拒绝，
零分母保留 NULL。输入/输出上限为 10,000 行、16 MiB，关联前估算膨胀；不静默截断。
Decimal 计算精度显式为 50 位；保留各源采集时间，不假设跨库一致性快照。
本地计算和表格展示不会因 NULL 将整数提前转为浮点数；
重复度量标记随连续关联及列重命名传递，不能通过追加一次 Join 绕过重复计数检查。

外部步骤可以先搜索再抓正文，也可直接获取 HTTP(S) 文档/结构化 API，或按能力调用
标准 MCP 工具。搜索摘要仅为 discovery，不允许当作结论证据。
`evidence_need` 明确 variable、region、unit、绝对 start/end；
文本抽取校验原文位置及各值，结构化 API 可用 `field_mapping` 声明 records_path、
value/unit/region/observed_at/variable 字段，保留 JSON Pointer。时间、地区、单位不匹配的
事实排除并记录警告；无匹配事实为证据不足。发布时点与观测时点分别保留，未知不补造。
结论中的外部数值使用 `{"step_id": 1, "fact_index": 0, "value": "12.5"}` 绑定到
该步骤持久结果的 `data.facts`；代码核对值和类型，并附上实际来源 URL 与正文位置或 JSON Pointer。
原有表格数值的 `step_id` / `column` / `row` 绑定保持兼容。
实际模型/工具调用均计入独立预算，外部抓取有超时和 2 MiB 文档预算。

本地标准 MCP stdio fixture 已验证真实协议协商、发现、调用与错误，Streamable HTTP 也有
本地服务协议测试。固定版本 Sequential Thinking 已完成真实多次调用；Fetch 初始化与发现
通过，但当前网络 DNS 返回 `198.18.x.x`，包括 Microsoft Learn 在内的正文抓取被默认地址
限制拒绝，尚未验收通过。没有启用绕过限制的选项；远程第三方 MCP、真实搜索/第三方 API 仍未联调。

### 统一工具与执行优化（T0-T5）

导航“工具”统一展示本地、内置 legacy RPC 和标准 MCP，三者不混称协议。
本地能力包括数据库查询/元数据/预览、内部知识检索，以及 Join、分组求和、比率、差值。
数据库连接仍在数据源页维护；计算只接受当前运行的已完成依赖，不提供任意 Python 执行。
计算保留旧 `output` 列名参数；输出单位跟随新列，比率保留分子/分母单位，同单位相除为
`ratio`，不同单位保留商的单位表达式，缺失单位明确警告而不猜测。
工具卡可设置类别、启用状态、适用说明、超时和并发上限；计算演示明确标为 SAMPLE。

添加 MCP 的流程为：选择类别及模板 → 填写连接与 capability 映射 → 保存禁用配置 →
确认可能下载/执行第三方包 → 测试并发现实际 Schema → 逐工具确认类别、只读策略与开关 →
启用服务器 → 需要时选择 capability 默认提供方。多提供方无明确选择时拒绝猜选。
新建与编辑服务器分开，同名新增不会覆盖现有连接；编辑后重新保存为禁用状态。
打开页面和读取目录不探测网络，也不自动安装或启动服务。

预置模板固定为 `uvx mcp-server-fetch==2026.10.10` 和
`npx -y @modelcontextprotocol/server-sequential-thinking@1.0.0`。
需要对应的 uvx / Node.js+npx；第三方依赖留在其隔离环境，不升级本项目锁定依赖。
stdio 使用程序、字符串参数数组、可选工作目录及 `env_refs`；
HTTP 使用标准 Streamable HTTP endpoint 和 `header_refs`，不是普通 REST 或 SSE URL。
引用格式为 `{"Authorization":"GENBI_MCP_AUTH"}`，读取该本机环境变量的完整头值，
不将值发送给规划器或保存到普通导出；首版不实现第三方 OAuth 授权流程。

目录同时生成规划候选、兼容注册表与执行定义。新计划记录 `tool_id`、`capability`、
`tool_version`，运行冻结连接和定义；实时禁用会阻止后续新调用，不伪称中断在途工作。
重复发现的时间戳不改变工具定义版本；历史运行仅在冻结定义仍匹配时兼容旧指纹，
真实 Schema、连接或策略变化仍拒绝静默替换。
规划目录按相关性选取最多 12 个工具，描述与 Schema 上下文总量不超过 24 KiB，不截断 Schema 后执行。
Sequential Thinking 仅用于复杂规划的可选子循环，最多 3 次调用；同运行有状态会话串行、
跨运行隔离，默认关闭，日志/回放只保留公开摘要与计数，不把规划说明当作数值事实。
Fetch 的截断、非零 `start_index` 或未知完整性保留为 discovery，不把分页末页冒充完整正文或可计算观测。

同步计划 API 与持久任务复用同一 DAG、调用核心和运行队列，合计最多 4 个活动运行、16 个排队运行，
每运行最多 4 步；全局步骤、工具许可与 MCP 会话分别最多 16 个，运行内会话最多 4 个，
空闲 60 秒回收。队列满返回 HTTP 503、`Retry-After`；持久任务同时返回关联 `run_id`，终态后可以创建重试。
许可等待有界、可取消；数据库在途调用仍以适配器实际超时和协作式取消为准。
工具尝试与模型重试各自记账，不按“步骤开始”重复计入工具预算；工具额度用尽不阻塞仅使用模型的
分析或用户澄清，但后续工具调用仍受限。

工具配置保存在忽略提交的 `config/tools_config.json`，连接和能力到工具名的映射仍仅在
`mcp_config.json`；自动发现快照单独缓存，不是可编辑的第二份工具 Schema。
目录定义最多缓存 16 个版本、发现快照最多保留 64 个服务器。知识分块/分词/文档频率/
倒排项预计算，最多缓存 8 个内容版本；内容变更失效，冻结旧任务仍使用自己的知识快照。
大于 4 MiB 的语料不进入共享索引缓存，检索语义与稳定片段引用保持不变。

聊天按会话分页读取摘要，展开才加载历史详情；运行中只在版本变化时重读状态，产物按不可变
ID 复用，等待输入和终态停止轮询。事件每页最多 500 条，继续按游标补读；JSON 与 CSV 导出
都在用户点击生成时创建，不在自动刷新中反复回放或导出。
每个浏览器会话的状态、产物和事件缓存共享 64 MiB 估算驻留预算，并保留每类最多 128 条限制；
按最近访问淘汰，超大条目完整返回但不驻留缓存，不截断事件或影响导出。公开状态读取不加载私有
配置快照，取消检查使用仅返回状态的轻量查询。

新增接口：

| 接口 | 用途 |
|---|---|
| `GET /api/tools`、`GET /api/tools/templates` | 脱敏目录及固定模板 |
| `PUT /api/tools/servers/{id}` | 保存禁用服务器配置；已有 ID 需显式 `replace_existing: true` |
| `POST /api/tools/servers/{id}/discover` | `{"confirmed":true}` 主动探测与发现 |
| `POST /api/tools/servers/{id}/enabled` | `{"enabled":true/false}` 启用/禁用 |
| `PUT /api/tools/definitions/{tool_id}` | 更新逐工具类别/开关/策略 |
| `PUT /api/tools/providers/{capability}` | 设置明确默认 `tool_id` |
| `POST /api/tools/trial` | 使用统一校验与预算试运行，不提供任意产物/文件引用 |
| `GET /api/runs/history?session_id=...&limit=20&before=...` | 分页摘要及 `next_cursor`，支持 `statuses` 筛选 |

旧 `/api/mcp/execute` 保留前缀白名单和兼容输出，同时遵守工具开关与调用许可。
旧精确 capability 映射保持原提供方，不因新增本地 Fetch 或新模板静默改道；
尚未发现 Schema 的旧连接不作为通用规划候选。旧 `/api/runs` 历史列表接口保留。

离线回归不下载第三方包。获得执行授权后，可显式运行：

```bash
GENBI_REAL_MCP=1 .venv/bin/python -m unittest tests.test_mcp_packages -v
```

Fetch 可通过 `GENBI_FETCH_URL` 指定公开页面；当前 DNS 环境下该正文测试会明确失败，
需在正常公网解析环境重试，不应启用 `--allow-private-ips` 来将失败包装为通过。
普通 HTTPS 可访问并不能证明 Fetch 的地址检查通过：本次排查中普通请求返回 HTTP 200，
但系统解析得到的 `198.18.x.x` 属于非公网地址，Fetch 在发送 robots 请求前就拒绝访问，
不是网站 robots 规则拒绝。详见 [Fetch 联网排查](mcp_servers/README.md#fetch-联网排查)。
各阶段完成标记及真实联调边界见 [optimize.md 第 17.10 节](optimize.md#1710-实施阶段与依赖)。

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
