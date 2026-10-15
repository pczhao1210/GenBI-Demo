# 内置工具服务器

这里的脚本提供 GenBI 内部的**换行 JSON RPC**，不是完整 MCP 2025 协议实现。
当前没有 `initialize` 协议协商、标准 `tools/list` / `tools/call` 或 SSE 传输，
不能直接作为任意第三方 MCP 客户端或服务器的替代品。

## 调用模式

每次调用根据配置启动一个脚本，发送一行 JSON，接收响应，然后退出。
“启用 / 禁用”控制是否允许按需调用，不代表启动 / 停止常驻进程。
配置的 `command`、`args` 会实际使用；`python` / `python3` 自动映射到当前解释器。
工作目录始终是仓库根目录，调用有超时。

请求示例：

```json
{"method":"get_server_info","params":{}}
```

成功响应的业务对象在 `result` 中；失败使用 `error`。
客户端会将嵌套的 `result.error` 提升为失败，不会转换为成功。
`get_server_info` 无需数据库凭据，也不验证数据库连接。

## 内置脚本

| 脚本 | 方法 |
|---|---|
| [mysql_server.py](mysql_server.py) | `get_server_info`、`execute_query`、`get_tables`、`describe_table`、`get_database_stats` |
| [athena_server.py](athena_server.py) | `get_server_info`、`execute_query`、`get_tables`、`describe_table` |
| [playwright_server.py](playwright_server.py) | `get_server_info`、`search_web`、`fetch_page` |

数据库方法通过 `params.config` 传递连接配置。
查询只允许单条只读 SELECT / WITH；应始终使用只读数据库账号和最小权限 IAM。
MySQL 连接池仅存在于单次子进程生命周期，不跨请求复用。
Athena 使用元数据 API 枚举表和字段，包含分区字段，不探测硬编码表名。

中央工具注册表提供 `mysql_query`、`mysql_describe_table`、`athena_query`、
`athena_describe_table`、`web_search`、`web_fetch` 六个工具。
工具参数使用 JSON Schema 校验，包含嵌套必填项、类型和范围。

网页功能需要安装 Chromium：

```bash
.venv/bin/python -m playwright install chromium
```

网页内容是外部证据，不保证搜索覆盖率或真实性。缺少浏览器、搜索失败或没有结果时，
分析步骤报告错误，不使用模拟信息。抓取输出目前仅支持文本。

## 扩展边界

管理页面可配置遵循上述内部请求 / 响应格式的 stdio 脚本。
自定义脚本的 `get_server_info` 可用于探测；内置业务路由和六个工具仍需在代码中注册。
标准 MCP 另有独立适配器，保留这里的内置兼容层。管理页可添加：

```json
{
  "observations": {
    "protocol": "mcp",
    "type": "streamable_http",
    "url": "http://localhost:9000/mcp",
    "status": "active",
    "timeout": 30,
    "capabilities": {"external.observation": "get_observation"}
  }
}
```

标准适配支持 stdio（`command` / `args`）和 Streamable HTTP，执行 initialize、
tools/list 与 tools/call，保留结构化内容并显式传播工具错误。SSE 未实现。
能力需明确映射到工具名；多个活动提供方有歧义时拒绝调用，不自动猜选。
测试使用真实本地标准 stdio fixture 验证发现、调用与错误，并通过本地 HTTP 服务验证
Streamable HTTP 调用；尚未与第三方远程服务器联调。
