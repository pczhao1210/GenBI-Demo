# GenBI - 生成式BI查询系统

基于大模型的智能数据库查询和分析平台，支持自然语言转SQL查询和智能数据分析。

## ✨ 功能特性

- 🤖 **智能SQL生成**: 纯LLM驱动的自然语言转SQL，支持复杂查询
- 📊 **智能意图识别**: 自动区分查询、分析和危险操作
- 🔒 **多层安全防护**: LLM意图识别 + SQL安全检测，防止数据修改
- 🗂️ **多表Schema管理**: 可视化配置数据库表结构和字段描述
- 🔗 **多数据源支持**: MySQL (含SSL) 和 AWS Athena
- 📋 **折叠式界面**: Schema提示默认折叠，界面更简洁
- 🛠️ **MCP协议集成**: 可扩展的工具生态系统
- 📋 **完整API**: RESTful API接口支持

## 🚀 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone <repository-url>
cd GenBI-Demo

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
source .venv/bin/activate  # Linux/Mac
# 或
.venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 一键启动（推荐）

```bash
# 使用启动脚本
chmod +x start.sh
./start.sh
```

### 3. 手动启动

```bash
# 启动后端API服务
cd backend
uvicorn main:app --reload --port 8000

# 启动前端Streamlit应用（新终端）
streamlit run app.py --server.port 8501
```

### 4. 访问应用

- **前端界面**: http://localhost:8501
- **API文档**: http://localhost:8000/docs  
- **API状态**: http://localhost:8000/health

## 🎯 使用指南

### 配置流程

1. **LLM配置** 
   - 支持OpenAI、Azure OpenAI、自定义API
   - **最新优化**: 修复了OpenAI API连接问题和参数兼容性
   - 自动适配不同模型的参数要求

2. **数据库配置** 
   - 支持MySQL (含SSL连接) 和AWS Athena
   - **增强功能**: 自动连接测试和详细错误提示
   - 支持复杂数据类型的JSON序列化

3. **Schema配置** 
   - 可视化设置数据库表结构和字段描述
   - **UI改进**: 折叠式Schema显示，界面更简洁
   - 支持多表关联和字段描述

4. **开始查询** 
   - 在聊天界面进行自然语言查询和分析
   - **智能清理**: 自动过滤SQL响应中的解释性文本

### 🧠 智能意图识别

系统使用增强的LLM意图识别：
- **查询意图**: "哪些产品是畅销品" - 直接执行数据查询
- **分析意图**: "分析销售趋势并给出建议" - 生成分析计划
- **拒绝意图**: 自动拒绝危险的增删改操作
- **优化改进**: 更准确区分简单查询和复杂分析需求

### 📊 支持的查询类型

- **直接查询**: "显示前10行数据", "哪些产品是畅销品"
  - 立即执行SQL查询并返回结果
  - **新增**: 自动清理SQL响应，只保留纯净数据

- **复杂分析**: "分析销售趋势并给出建议"
  - 系统先生成详细分析计划
  - 用户可以补充或修改计划
  - 输入"执行"开始多步骤分析

- **统计查询**: "统计每个月的订单数量"
  - 支持聚合函数和分组统计
  - 自动生成可视化建议

### 🔒 多层安全防护

- **智能意图识别**: 增强的LLM分类，准确识别用户意图
- **SQL安全检测**: 代码级别检查，防止危险操作
- **数据修改拦截**: 自动拒绝INSERT/UPDATE/DELETE操作
- **错误处理优化**: 完善的异常捕获和用户友好提示
- **API限制处理**: 智能重试机制和频率限制应对

## 📁 项目结构

```
GenBI-Demo/
├── 📱 app.py                     # Streamlit主应用入口
├── 📄 start.sh                   # 一键启动脚本
├── 🔧 requirements.txt           # Python依赖包
├── 📖 README.md                  # 项目文档
├── 
├── 📁 pages/                     # Streamlit页面组件
│   ├── 💬 chat.py                # 智能聊天界面（已优化）
│   ├── 🗄️ database_config.py     # 数据库配置页面
│   ├── 🤖 llm_config.py          # LLM配置页面（已优化）
│   ├── 📋 schema_config.py       # Schema配置页面
│   ├── 🔧 mcp_management.py      # MCP服务管理
│   └── 📚 api_docs.py            # API文档页面
├── 
├── 📁 backend/                   # FastAPI后端服务
│   ├── 🚀 main.py                # FastAPI应用主入口
│   └── 📁 routers/               # API路由模块
│       ├── 💬 chat.py            # 聊天API
│       ├── 🗄️ database.py        # 数据库API
│       ├── 🤖 llm.py             # LLM服务API
│       └── 🔧 mcp.py             # MCP协议API
├── 
├── 📁 config/                    # 配置文件目录
│   ├── 🗄️ database_config.json     # 数据库连接配置
│   ├── 🤖 llm_config.json          # LLM服务配置
│   ├── 🔧 mcp_config.json          # MCP服务器配置
│   ├── 📋 schema_config.json       # 数据库表结构配置
│   ├── 📄 example_database_config.json  # 数据库配置模板
│   ├── 📄 example_llm_config.json      # LLM配置模板
│   └── 📄 example_mcp_config.json      # MCP配置模板
├── 
├── 📁 utils/                     # 核心工具模块
│   ├── ⚙️ config_manager.py      # 配置管理器
│   ├── 🤖 llm_client.py          # LLM客户端（已优化）
│   ├── 🔧 mcp_client.py          # MCP客户端
│   ├── 📋 mcp_tools_registry.py  # MCP工具注册中心
│   ├── 🛠️ mcp_tool_handler.py    # MCP工具调用处理器
│   └── 🌐 i18n.py               # 国际化支持
├── 
├── 📁 mcp_servers/               # MCP协议服务器
│   ├── 🗄️ mysql_server.py        # MySQL服务器（已优化）
│   ├── ☁️ athena_server.py       # AWS Athena服务器
│   ├── 🌐 playwright_server.py   # Web搜索服务器
│   └── 📋 MCP_TOOLS_SPECIFICATION.md # MCP工具规范文档
├── 
└── 📁 test/                      # 测试和文档文件
    ├── 📖 README_ENHANCED.md     # 增强版文档
    ├── 📖 SETUP.md              # 设置指南  
    ├── 📖 mcp_readme.md         # MCP说明文档
    └── 🧪 *.py                   # 测试脚本
```

## 🔧 MCP协议集成

本项目完全支持**Model Context Protocol (MCP) 2025-06-18规范**，提供动态可扩展的工具生态系统。

### MCP核心特性
- � **动态服务器发现**: 实时检测和配置MCP服务器
- 📋 **工具注册系统**: 中央化管理6个标准MCP工具
- 🔗 **OpenAI Functions集成**: 自动转换MCP工具为LLM可用格式
- ✅ **JSON Schema验证**: 完整的参数验证和类型安全
- 🛡️ **安全标记**: 破坏性操作识别和受众目标管理

### 内置MCP工具
- 🗄️ **数据库查询**: `athena_query`, `mysql_query` - 执行SQL查询
- 📋 **表结构**: `athena_describe_table`, `mysql_describe_table` - 获取表信息
- 🌐 **Web工具**: `web_search`, `web_fetch` - 网页搜索和内容获取

### MCP服务器
- �️ **MySQL服务器**: 支持SSL连接和复杂查询
- ☁️ **Athena服务器**: AWS数据仓库查询支持
- 🌐 **Playwright服务器**: 现代Web抓取和搜索

### 文档资源
- 📖 **[MCP工具规范](mcp_servers/MCP_TOOLS_SPECIFICATION.md)** - 完整的MCP实现文档
- � **动态配置**: 通过MCP管理页面实时配置服务器
- �️ **自定义扩展**: 支持创建符合MCP 2025规范的自定义服务器

## 🏗️ 技术架构

### 系统设计
- **前端界面**: Streamlit提供现代化交互式用户界面
- **后端服务**: FastAPI提供高性能RESTful API（可选）
- **配置存储**: 本地JSON文件存储配置和Schema
- **LLM集成**: 支持OpenAI、Azure、自定义API等多种提供商

### 🎯 核心能力
- **增强意图识别**: 使用优化的LLM Prompt准确识别用户查询意图
- **多轮对话分析**: 复杂分析任务支持计划生成和迭代优化
- **可视化Schema管理**: 折叠式界面配置和管理数据库表结构
- **多层安全防护**: LLM+代码双重检查防止危险操作
- **智能错误处理**: 完善的重试机制、类型转换和错误恢复
- **MCP 2025规范**: 完全符合最新MCP协议，支持动态工具发现和调用
- **工具生态系统**: 可扩展的MCP工具注册和管理系统

## 🔄 最新更新日志

### v3.0.0 (当前版本) - MCP协议全面升级
- ✅ **MCP 2025-06-18规范**: 完全符合最新Model Context Protocol标准
- ✅ **动态工具发现**: 实时MCP服务器检测和工具注册系统
- ✅ **工具注册中心**: 统一管理6个标准MCP工具，支持JSON Schema验证
- ✅ **OpenAI Functions集成**: MCP工具自动转换为LLM可调用格式
- ✅ **服务器状态监控**: 实时健康检查和能力更新
- ✅ **安全增强**: 破坏性操作标记和受众目标管理
- ✅ **文档完善**: 完整的MCP实现规范文档
- ✅ **向后兼容**: 保持所有原有功能的同时增加MCP能力

### v2.1.0 (之前版本)
- ✅ **OpenAI API修复**: 解决连接错误和JSON解析问题
- ✅ **模型兼容性**: 优化参数设置，支持gpt-5-mini等最新模型
- ✅ **意图识别优化**: 更准确区分"查询"和"分析"类型请求
- ✅ **UI/UX改进**: Schema提示默认折叠，界面更简洁友好
- ✅ **数据处理增强**: SQL响应自动清理，Decimal类型序列化支持

## 📚 文档和API

- **API文档**: http://localhost:8000/docs (交互式Swagger文档)
- **MCP工具规范**: [mcp_servers/MCP_TOOLS_SPECIFICATION.md](mcp_servers/MCP_TOOLS_SPECIFICATION.md) - 完整的MCP实现文档
- **项目计划**: [GenBI_Project_Plan.md](GenBI_Project_Plan.md) - 项目发展路线图

## 🤝 贡献指南

我们欢迎各种形式的贡献！

### 提交代码
1. Fork项目到自己的仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开Pull Request

### 代码规范
- 遵循PEP 8 Python代码规范
- 添加必要的测试用例和文档
- 确保所有测试通过

## 📞 支持和反馈

如遇问题或有建议，请：
- 📝 提交 [GitHub Issue](issues)
- 📧 发送邮件反馈
- 💬 参与讨论和改进

## 📄 许可证

本项目基于 **MIT License** 开源协议 - 详见 [LICENSE](LICENSE) 文件

---

**GenBI** - 让数据查询变得智能和简单！ 🚀