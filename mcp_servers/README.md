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

“工具”页面保留已有内部脚本的启用、禁用、扫描及主动探测；新增第三方服务器走标准 MCP。
自定义旧脚本的 `get_server_info` 可用于探测，但不会因扫描到名称就自动进入通用规划器。
兼容注册表由统一目录生成，仍支持原六个别名与 `database_*` 的明确数据源入口。
标准 MCP 使用独立适配器，保留这里的内置兼容层；配置格式示例：

```json
{
  "observations": {
    "protocol": "mcp",
    "type": "streamable_http",
    "url": "http://localhost:9000/mcp",
    "status": "inactive",
    "timeout": 30,
    "capabilities": {"external.observation": "get_observation"}
  }
}
```

标准适配支持 stdio（`command` / `args`）和 Streamable HTTP，执行 initialize、
tools/list 与 tools/call，保留文本/结构化内容并显式传播工具错误。SSE 未实现。
页面保存为禁用；用户确认测试可能下载/运行第三方包后，主动发现 Schema、配置类别和只读策略、
逐工具确认，再启用服务器。读取 `/api/tools`、打开页面或默认 `/api/mcp/status` 不启动服务。
能力需明确映射到工具名；多个活动提供方有歧义时拒绝调用，不自动猜选。
测试使用真实本地标准 stdio fixture 验证发现、调用与错误，并通过本地 HTTP 服务验证
Streamable HTTP 调用；尚未与第三方远程服务器联调。

固定模板为 Fetch `2026.10.10`（uvx）和 Sequential Thinking `1.0.0`（npx）。
它们在独立环境中运行，不是把源码内嵌进 GenBI，也不因打开页面自动安装。
有状态规划辅助使用运行拥有的稳定异步上下文，最多 3 次辅助调用，同运行串行、跨运行隔离；
结束、等待用户、失败和取消后关闭会话。原始 `thought` 不进入事件、回放或导出，
同时设置 `DISABLE_THOUGHT_LOGGING=true`；工具输出不是观测证据。

Sequential Thinking 已完成真实多次调用。Fetch 已完成真实握手、发现与调用发起，但
当前网络将 Microsoft Learn 等公网域名解析为 `198.18.x.x`，被 Fetch 默认地址限制拒绝，
尚未通过真实正文验收。保持地址及 robots 限制，不添加绕过选项或用其他抓取器冒充成功。
标准连接的认证使用环境变量引用；完整 OAuth 流程不在首版范围内。

### Fetch 联网排查

2026-10-17 使用缓存中的固定包 `mcp-server-fetch==2026.10.10` 重新验证：
普通 HTTPS 请求访问 example.com 返回 HTTP 200，两个站点的 robots 端点也能收到 HTTP 响应；
但系统 DNS 将 example.com 和 learn.microsoft.com 解析为 `198.18.x.x`。
该地址段不是公网地址，符合 Fake-IP/透明代理环境中“普通客户端能访问，地址校验拒绝”的现象。

Fetch 的 `check_may_autonomously_fetch_url()` 先请求 robots，发送请求前的
`_refuse_private_destination()` 会用系统 DNS 解析目标，随后通过 `_is_public_address()` 检查。
本次在这个请求前置检查中就报 `not a public address`，并未读取到 robots 规则，
不是网站拒绝爬取、包未安装、MCP 初始化失败，也不是本次进程缺少代理环境变量
（父进程没有设置 HTTP/HTTPS/ALL_PROXY）。

GenBI 现在会展开 MCP transport 的嵌套异常，显示底层地址拒绝等真实错误，不再只显示
`ExceptionGroup: unhandled errors in a TaskGroup`；规划辅助工具仍隐藏可能包含原始内容的错误详情。

排查顺序：

1. 比较系统 DNS 返回的地址与普通 HTTPS 连通性，不能只看浏览器能否打开网页。
2. 如果正在使用 Fake-IP，需在上游 DNS/代理配置中让目标域名返回真实公网地址
   （例如配置对应域名的 Fake-IP 排除规则），或在正常公网 DNS 环境运行 Fetch。
3. 重新进行固定包的正文获取与分页验收；解析正常后仍需遵守站点 robots 规则。

本轮未修改系统 DNS、代理、真实服务器连接，也未关闭地址或 robots 限制。真实正文验收仍待完成；
不能用普通 HTTP 请求成功替代 MCP Fetch 验收。
