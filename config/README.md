# 配置说明

实际配置由页面保存，已排除在版本控制之外；`example_*.json` 只包含占位符。
不要提交真实凭据。配置文件位置相对于仓库根目录，不随启动工作目录变化。

| 文件 | 用途 |
|---|---|
| `database_config.json` | MySQL / Athena 连接配置，根键 `databases` |
| `llm_config.json` | LLM 配置，根键 `llm_config` |
| `schema_config.json` | 表结构和业务描述，根键 `schemas` |
| `mcp_config.json` | 内置 stdio RPC 脚本配置，根键 `mcp_servers` |

缺少 LLM、数据库或 Schema 配置时明确报错，不自动使用模板中的假凭据。
工具配置仅在文件不存在时从[示例](example_mcp_config.json)初始化；
显式保存空工具列表不会恢复已删除的工具。

配置写入采用同目录临时文件和原子替换。数据库 / Schema 读改写使用文件锁，
防止并发保存不同类型时覆盖彼此。`*.lock` 文件是锁元数据，不需要提交或备份。
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

## Schema

当前 MySQL、Athena 各保存一套 Schema，不支持同类型的多个独立数据库配置。
连接变更后需要重新获取和保存 Schema。页面编辑状态按连接隔离，
只在首次进入该连接时载入磁盘配置，不会每次重跑覆盖未保存编辑。
“清空配置”会持久清空当前数据库类型的表结构和描述。

## 工具

`status: "active"` 允许按需调用，`inactive` 禁止业务调用；
脚本信息探测不受启用状态影响。首次初始化默认启用三个内置工具。
支持实际的 `command` / `args` 配置和可选的进程 `timeout`（秒）。
当前只支持内部 stdio RPC，不支持 SSE 或完整 MCP 协议。
