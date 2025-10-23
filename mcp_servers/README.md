# MCP 服务器 - Model Context Protocol

本目录包含符合 **MCP 2025-06-18 规范** 的Model Context Protocol服务器实现。

## 📁 文件结构

```
mcp_servers/
├── 📋 README.md                    # 本文档
├── 📋 MCP_TOOLS_SPECIFICATION.md   # MCP工具完整规范文档
├── 🗄️ mysql_server.py             # MySQL数据库MCP服务器
├── ☁️ athena_server.py            # AWS Athena数据仓库MCP服务器
└── 🌐 playwright_server.py        # Web搜索和抓取MCP服务器
```

## 🔧 MCP 服务器

### MySQL 服务器 (`mysql_server.py`)
- **功能**: 提供MySQL数据库查询和表结构获取功能
- **工具**: `mysql_query`, `mysql_describe_table`
- **特性**: SSL连接支持，安全查询过滤

### AWS Athena 服务器 (`athena_server.py`)
- **功能**: 提供AWS Athena数据仓库查询服务
- **工具**: `athena_query`, `athena_describe_table`  
- **特性**: S3数据湖查询，大数据分析支持

### Playwright 服务器 (`playwright_server.py`)
- **功能**: 现代Web搜索和内容抓取
- **工具**: `web_search`, `web_fetch`
- **特性**: 动态网页支持，智能内容提取

## 🛠️ 开发指南

### 服务器规范
所有MCP服务器都遵循以下标准：
- **协议版本**: MCP 2025-06-18
- **服务器信息**: 实现 `get_server_info()` 方法
- **工具定义**: 完整的JSON Schema参数验证
- **错误处理**: 标准化错误代码和响应格式

### 工具定义标准
```python
{
    "name": "tool_name",
    "description": "工具描述",
    "inputSchema": {
        "type": "object", 
        "properties": {...},
        "required": [...]
    }
}
```

### 扩展新服务器
1. 继承基础MCP服务器模式
2. 实现 `get_server_info()` 方法
3. 定义工具的JSON Schema
4. 添加到MCP工具注册中心
5. 在MCP管理页面配置

## 📖 详细文档

完整的MCP实现文档请参考：
**[MCP_TOOLS_SPECIFICATION.md](MCP_TOOLS_SPECIFICATION.md)**

包含内容：
- MCP协议完整规范
- 工具注册系统详解
- 服务器开发指南
- 错误处理最佳实践
- OpenAI Functions集成
- 动态服务器发现机制

---

**GenBI MCP生态系统** - 让AI工具调用变得智能和可扩展！ 🚀