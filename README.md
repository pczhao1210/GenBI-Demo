# GenBI - 生成式BI查询系统

[English](README_en.md) | 中文

基于大模型的智能数据库查询和分析平台，支持自然语言转SQL查询和智能数据分析。

## 功能特性

- 🤖 **智能查询**: 自然语言转SQL查询
- 📊 **数据分析**: AI驱动的数据洞察  
- 🔗 **多数据源**: 支持AWS Athena和MySQL
- 🛠️ **MCP集成**: 可扩展的工具生态 ([详细文档](mcp_servers/mcp_readme.md))
- 📋 **API接口**: 完整的RESTful API

## 快速开始

### 1. 环境准备

```bash
# 激活虚拟环境
source .venv/bin/activate  # Linux/Mac
# 或
.venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 启动服务

```bash
# 启动后端API服务
cd backend
uvicorn main:app --reload --port 8000

# 启动前端Streamlit应用
streamlit run app.py --server.port 8501
```

### 3. 访问应用

- 前端界面: http://localhost:8501
- API文档: http://localhost:8000/docs
- API状态: http://localhost:8000/health

## 使用指南

### 配置流程

1. **LLM配置** - 配置OpenAI、Azure OpenAI或自定义LLM服务
2. **数据库配置** - 连接AWS Athena或MySQL数据库
3. **Schema配置** - 设置数据库表结构和字段描述（必需）
4. **开始查询** - 在聊天界面进行自然语言查询和分析

### 智能意图识别

系统使用LLM自动识别用户意图：
- **查询意图**: 直接执行数据查询
- **分析意图**: 生成分析计划，支持多轮对话完善后执行
- **拒绝意图**: 自动拒绝危险的增删改操作

### 支持的查询类型

- **直接查询**: "显示前10行数据"
- **数据分析**: "分析销售趋势并给出建议"
  - 系统会先生成分析计划
  - 用户可以补充或修改计划
  - 输入"执行"开始分析
- **统计查询**: "统计每个月的订单数量"

### 安全特性

- **双重安全检查**: LLM意图识别 + SQL代码检测
- **危险操作拦截**: 自动拒绝INSERT/UPDATE/DELETE等操作
- **频率限制处理**: 自动重试机制处理API限制

## 项目结构

```
GenBI-Demo/
├── app.py                  # Streamlit主应用
├── pages/                  # 页面组件
├── backend/                # FastAPI后端
├── config/                 # 配置文件
├── utils/                  # 工具模块
├── mcp_servers/            # MCP服务器
└── requirements.txt        # 依赖包
```

## MCP集成

本项目支持MCP (Model Context Protocol) 服务器扩展，提供可插拔的工具生态系统。

- 📖 **[MCP开发指南](mcp_servers/mcp_readme.md)** - 详细的MCP服务器配置和开发文档
- 🔧 **内置服务器**: MySQL、AWS Athena数据库连接器
- 🛠️ **自定义扩展**: 支持创建自定义MCP服务器
- 🔗 **标准协议**: 基于MCP标准协议，确保兼容性

## 技术特性

### 架构设计
- **前端**: Streamlit提供交互式用户界面
- **后端**: FastAPI提供RESTful API服务（可选）
- **存储**: 本地JSON文件存储配置和Schema
- **LLM集成**: 支持多种LLM提供商和自定义API

### 核心功能
- **智能意图识别**: 使用LLM准确识别用户查询意图
- **多轮对话分析**: 分析任务支持计划生成和迭代优化
- **Schema管理**: 可视化配置和管理数据库表结构
- **安全防护**: 多层安全检查防止危险操作
- **错误处理**: 完善的重试机制和错误恢复

## 许可证

MIT License