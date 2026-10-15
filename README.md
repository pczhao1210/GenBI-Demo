# GenBI - 生成式 BI 查询系统

使用自然语言查询 MySQL / AWS Athena，并生成基于查询证据的多步骤分析报告。

## 当前能力

- Streamlit 配置与聊天界面，中文 / English 切换。
- OpenAI、Azure OpenAI、OpenAI SDK 和自定义 HTTP LLM。
- Schema 编辑与业务描述，按数据源隔离编辑状态。
- 单条只读 SQL 校验，支持 `SELECT`、CTE、聚合、关联和集合查询。
- 分析计划生成、修改、确认执行、取消与重新执行。
- 查询结果、分析报告和错误保留在当前会话；切换数据源不会混用计划。
- 前端与 FastAPI 复用同一业务服务，不返回模拟查询或连接成功。
- 内置数据库 / 网页工具的按需 stdio 调用。

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
   清空操作会持久清空**当前数据库类型**的 Schema，不影响另一种类型。
5. **聊天**：查询直接执行；复杂分析先展示计划，再点击执行或输入修改意见。
   计划绑定当前连接和 Schema；失败或被跳过的步骤不会显示为完成。

配置当前按 `mysql` / `athena` 各保存一套连接与 Schema，不是多租户数据库目录。
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
- 聊天历史和报告保存在当前 Streamlit 会话中，浏览器会话结束后不保证保留。
- 当前工具是内置换行 JSON RPC 兼容层，**不是完整 MCP 2025 协议实现**，
  不支持 SSE 或任意第三方 MCP 服务器。详见[工具说明](mcp_servers/README.md)。
- 默认只监听本机；当前没有多用户认证或租户隔离，不应直接公开到互联网。
- 图表、收藏、跨会话历史和持续性能指标尚未实现。

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

## 许可证

[MIT License](LICENSE)。
