# 配置说明

实际配置由页面保存，已排除在版本控制之外；`example_*.json` 只包含占位符。
不要提交真实凭据。配置文件位置相对于仓库根目录，不随启动工作目录变化。

| 文件 | 用途 |
|---|---|
| `database_config.json` | MySQL / Athena 连接配置，根键 `databases` |
| `llm_config.json` | LLM 配置，根键 `llm_config` |
| `schema_config.json` | 表结构和业务描述，根键 `schemas` |
| `mcp_config.json` | 内置 legacy RPC / 标准 MCP 连接及 capability 映射，根键 `mcp_servers` |
| `tools_config.json` | `schema_version: 1`；类别、逐工具覆盖、调用限制与默认提供方 |
| `tool_discovery.json` | 自动发现快照、连接指纹、时间与 Schema 指纹，不手工维护 |
| `datasources.json` | 多连接及每个连接的 Schema，根键 `sources` |
| `semantics.json` | KPI、实体、维度、物理映射与关系 |
| `knowledge.json` | 知识文档与知识库/业务主题（`scope`），根键 `documents` |
| `query_knowledge.json` | 问题导向的指导与关联资源，根键 `queries` |
| `methods.json` | 分析步骤模板、发布/验证记录和相似问题，根键 `methods` |
| `profiles.json` | 业务方向资源组合，根键 `profiles`，按稳定 Profile ID 保存 |
| `model_roles.json` | `fast` / `sql` / `reasoning` 的 `model_name`，共用全局连接；保留旧完整模型配置的兼容性 |
| `workflow_config.json` | 根键 `nodes`，节点角色/型号、可编辑 Prompt 与按 Profile 绑定的示例 |
| `model_catalog.json` | 提供商返回的型号列表、连接指纹和刷新时间，不存凭据 |

缺少 LLM、数据库或 Schema 配置时明确报错，不自动使用模板中的假凭据。
工具配置仅在文件不存在时从[示例](example_mcp_config.json)初始化；
显式保存空工具列表不会恢复已删除的工具。

配置写入采用同目录临时文件和原子替换。资源范围读改写使用可重入文件锁，
防止不同 Profile 并发保存时覆盖彼此的隐藏记录；数据库迁移另有文件锁。
`*.lock` 文件是锁元数据，不需要提交或备份。
JSON 损坏会显式报错，不会静默重置配置。

## Athena

[数据库模板](example_database_config.json)使用标准键：
`region`、`database`、`aws_access_key_id`、`aws_secret_access_key`、
`aws_session_token`（可选）、`workgroup`、`s3_output_location`、`max_rows`、
`query_timeout`。旧的 `access_key` / `secret_key` 仍可读取。
凭据留空时使用默认 AWS 凭据链。S3 输出位置也可以由 Workgroup 配置。

## LLM

[LLM 模板](example_llm_config.json)展示三个 HTTP 提供商。
`provider: "openai_sdk"` 使用 `openai` 配置段和实例级 SDK 客户端。
自定义请求模板、认证头和响应路径可在 JSON 中配置；页面保存时保留高级字段。
超时可为秒数，也可为 `query` / `analysis` / `default` 字典；空字典使用自动超时。
页面保存连接并刷新模型列表后，通过下拉选择默认型号、角色及节点型号。
角色格式如 `{"reasoning":{"model_name":"provider-model-id"}}`；不复制 API Key。
列表按连接指纹隔离，更改地址或凭据会使旧列表失效；旧型号/旧独立连接不自动替换。
模型列表接口不可用时显示错误，不能用预置假型号冒充发现成功。

## Schema

当前按稳定 `datasource_id` 保存多连接，支持同类型多个独立数据库。
旧 MySQL/Athena 配置自动迁移为 `legacy-mysql` / `legacy-athena`。
连接变更后需要重新获取和保存 Schema。页面编辑状态按连接隔离，
只在首次进入该连接时载入磁盘配置，不会每次重跑覆盖未保存编辑。
可直接编辑已保存表、离线添加表定义、增删字段和修改名称/类型/说明。
“清空配置”只清空当前可见表结构和描述；若 Profile、业务定义或查询知识仍引用它们，会阻止保存并要求先解除引用。
所有这些操作只修改应用配置，不执行数据库 DDL。

## Profile 与节点配置

优先使用「业务 Profile」「业务知识中心」「模型与 Prompt」页面，不要求手写 JSON。
Profile 示例结构：

```json
{
  "id": "sales",
  "name": "销售分析",
  "description": "订单与访问量分析",
  "datasources": {
    "orders-db": ["orders", "stores"],
    "traffic-db": ["visits"]
  },
  "mcp_servers": ["market-data"],
  "knowledge_ids": ["sales-definitions"],
  "method_ids": ["revenue-decomposition"],
  "query_ids": ["company-sales"],
  "status": "active"
}
```

活动 Profile 的资源必须存在，表列表不能为空。`status: "draft"` 可暂不绑定资源，但不能查询；
先创建草稿可为后续私有资源提供稳定的拥有者 ID。
Profile 使用文件锁和原子保存，不保存连接凭据副本。
任务快照冻结所选资源，SQL 与元数据在执行前按所选连接和表检查。
知识 `scope` 是检索主题，不是权限；Profile 以明确文档 ID 选择知识内容。

### 资源共享范围

连接、业务定义、知识文档、查询知识、方法/案例使用
`"visibility": "shared", "profile_id": null` 或 `"visibility": "profile", "profile_id": "sales"`。
未声明范围的历史普通记录按共享处理。共享资源可跨 Profile 发现和复用，但仍需显式勾选执行资源。
私有资源仅拥有者 Profile 可发现；模型和基础 Prompt 仍全局配置。
表级范围存放于连接的 Schema，字段及描述继承表范围，连接范围为上限：

```json
{
  "tables": {"orders": [{"name": "company_id", "type": "varchar"}]},
  "descriptions": {"orders": "每行一个订单行"},
  "table_scopes": {"orders": {"visibility": "profile", "profile_id": "sales"}}
}
```

共享定义/指导不能绑定私有资源；私有记录只能绑定共享或同拥有者资源。
保存时保留其他 Profile 的隐藏记录，删除/收窄已被引用的资源会被拒绝；
删除 Profile 前必须共享或删除它拥有的私有资源。切换 Profile 会丢弃未保存表单草稿。
这是业务范围隔离，不是用户鉴权或多租户授权系统。

### 查询 / 分析指南

```json
{
  "queries": [{
    "id": "company-sales",
    "question": "查询 A 公司本月净销售额",
    "guidance": "确认公司唯一 ID 和当前日期，使用净销售额口径汇总订单行；同名公司先澄清。",
    "visibility": "shared",
    "profile_id": null,
    "bindings": {
      "sources": {"orders-db": ["orders"]},
      "semantics": {"metrics": ["net_sales"], "entities": ["company"], "dimensions": ["month"]},
      "knowledge": ["sales-definitions"],
      "methods": ["revenue-decomposition"]
    }
  }]
}
```

必需 ID、问题或指南名称与处理方式；UI 自动生成稳定 ID，`bindings` 可省略。
可选 `examples` 为最多 8 条 `{"question":"另一种问法","guidance":"如何处理，需替换哪些参数"}`；
这些示例继承指南共享范围，帮助匹配和适配，不携带历史 SQL/答案，不是节点输出格式示例。
示例中的所有资源 ID 必须换成实际已有配置。Profile 选择该指导时，还要显式选择依赖的表、文档和方法。
词项检索最多匹配 3 条，关联知识片段最多每条 4 个；仅兼容且已发布的方法可优先推荐。
指导辅助理解/SQL/规划，不复用旧 SQL、数值或结论，不增加权限；公司和日期按当前问题重新确定。

节点可配置 `role`、`model_name`（省略则继承角色）、`prompt_template`（省略则加载真实默认 Prompt）、
`example_mode` 和 `examples`：

```json
{
  "nodes": {
    "sql_generation": {
      "role": "sql",
      "prompt_template": "Use only the supplied schema. Return one read-only SQL query only.",
      "example_mode": "one_shot",
      "examples": [
        {"visibility": "profile", "profile_id": "sales", "input": "Return one without reading a table", "output": "SELECT 1 AS value"}
      ]
    }
  }
}
```

`example_mode` 可选 `zero_shot`、`one_shot`、`few_shot`。新增共享示例必须显式声明 `visibility: "shared"`；
私有示例优先，然后共享；one-shot 取第一条，few-shot 合计最多 8 条。每个节点每个范围最多保存 8 条。
历史示例只有 `profile_id: null` 而没有 `visibility` 的，仍仅用于未选择 Profile 的兼容模式。
示例与编辑后的 Prompt 不绕过 Profile SQL/工具/知识限制；动态上下文和最终校验由代码管理。
旧的 `model` 完整配置和 `prompt` 补充指令仍可读取，UI 重新保存时改用新的模板字段。
配置及默认 Prompt 随新任务冻结，重试会检查兼容性。

知识中心使用统一目录和三种模板：指标/业务定义、查询/分析指南、参考资料。
独立对象/维度、可执行方法由高级模板创建，已有方法与案例保留 ID 并出现在同一目录。
每类表单保留编写示例；指标直接展示名称、定义、统计对象、分析维度四个输入框和各自示例。
条目高级 JSON 及底部批量 JSON 区也提供编辑或示例，不另设主 Tab。

新的指标表单要求名称和定义；对象和维度说明可选。保存格式如下：

```json
{
  "metrics": {
    "net_sales": {
      "name": "净销售额",
      "description": "订单行单价乘数量乘折扣，扣除退款后汇总",
      "subject": "按公司统计，基础数据为订单明细",
      "dimension_notes": "通常按自然月、地区或产品分析"
    }
  }
}
```

`entity_ids` / `dimension_ids` 可选，引用同范围或共享的对象/维度定义，不复制内容、不作为硬性维度白名单。
关联定义在运行范围外时不传入运行，保存管理视图不删除其他 Profile 的记录。
历史指标只含业务定义的最简 JSON 继续有效，无需批量迁移：

```json
{"metrics": {"kpi1": {"description": "KPI1 = A * B * C；A 为单价，B 为数量，C 为折扣系数，按订单行计算。"}}}
```

页面录入时 ID 可自动生成；JSON 的对象键仍用于稳定引用。
`formula`、`aggregation`、`unit`、`time_field`、`allowed_dimensions`、`mappings` 均可省略，不默认 `sum`。
省略维度列表表示交给查询时解析；显式维度列表（包括空列表）仍是约束。
未指定映射时，理解节点接收当前 Profile 内的 Schema，不接收连接凭据；有歧义先澄清，
后续 SQL / 规划使用业务定义及实际字段，不修改已保存定义。已有显式映射不会被自动改绑。
没有已保存 Schema 时要求补充 Schema，不能仅凭定义得出数值。
示例同时提供最简 KPI 和带可选结构化字段的记录数 KPI，后者有 Schema 时绑定第一张表。
方法草稿可保存空 `template.steps`；验证 / 发布阶段仍必须提供有效的非空步骤 DAG 和评审记录。
“载入示例”不写磁盘，实际保存仍需经过同样的资源校验和方法发布校验。

### 阶段检索与试用

普通用户无需选节点，默认适用阶段如下。高级设置写入 `retrieval_stages`，省略时继承默认；
显式空列表表示不参与自动检索，不是关闭 Profile 权限或已配置的业务约束。

| 内容 | 默认阶段 |
|---|---|
| 指标、对象、维度、参考文档 | `understanding`, `planning`, `sql_generation`, `analysis`, `explanation` |
| 查询/分析指南 | `understanding`, `planning`, `sql_generation`, `analysis` |
| 可执行方法、方法案例 | `planning`, `analysis` |

理解、规划和 SQL 节点始终携带当前范围内的定义及结构化约束，不依赖检索排名。
阶段上下文统一包含 `stage`、`guides`、`methods`、`documents`；方法仍需发布且满足工具/数据前提，
指南及关联片段不冒充当前数值证据。SQL 修复/重规划沿用对应阶段；结果表达只排列已验证结论，
不增加新的 RAG 事实。显式知识查询工具不以这些阶段标签作为权限控制。
配置继续分别保存在原文件，不复制 ID 或引用；任务快照冻结阶段配置和内容。

`GET /api/semantics/catalog?profile_id=...` 返回统一目录；
`GET /api/semantics/preview?q=...&stage=planning&profile_id=...` 与页面检索试用使用同一流程，
报告匹配内容、固定约束及未选择/缺少的关联资源。省略 Profile 使用共享运行范围；
草稿 Profile 不假装具备执行范围，需先激活。试用不调用 LLM 或数据库。

## 工具

`status: "active"` 允许按需调用，`inactive` 禁止业务调用；
脚本信息探测不受启用状态影响。首次初始化默认启用三个内置工具。
支持实际的 `command` / `args` 配置和可选的进程 `timeout`（秒）。
内置脚本仍使用内部 stdio RPC；标准 MCP 使用 `protocol: "mcp"`，
传输方式为 `stdio` 或 `streamable_http`，不支持 SSE。连接和 capability 到实际工具名
的映射只保存在本文件，不复制到工具配置中。

[工具配置示例](example_tools_config.json)中的类别使用稳定 ID；修改显示名称不改变工具身份。
覆盖键为 `local:database.query`、`local:knowledge.search`、
`local:compute.ratio` 或 `mcp:<server_id>:<tool_name>` 等稳定 `tool_id`。
默认提供方保存在 `default_providers`，一个能力有多个提供方时必须明确选择。
新增服务器默认保存为禁用；也可通过一键验证连接流程在发现成功后启用连接，但逐工具仍默认关闭。
发现失败保留禁用配置并报错。已有内置列表和旧标准 MCP 映射不改写。
未映射的发现工具获得稳定能力名 `mcp.<server_id>.<tool_name>`；不代表它自动具备数据库/搜索等标准语义。
工具开关立即保存，关闭后从规划候选中移除，并阻止新的调用。
新管理入口的单服务器/单工具读改写采用文件锁及原子保存，保留其他服务器及未知字段。

标准 stdio 可配置 `cwd`、`env_refs`，HTTP 可配置 `header_refs`；引用格式为
`{"目标变量或认证头名":"本机环境变量名"}`，不在配置中填写认证值。
发现缓存最多 64 个服务器，连接改变后必须重新发现；启用状态或工具覆盖改变会立即改变目录缓存键。
知识索引与目录的内存缓存有容量限制，缓存不是配置编辑入口。
