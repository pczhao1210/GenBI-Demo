import streamlit as st

st.set_page_config(
    page_title="GenBI - 生成式BI查询系统",
    page_icon="🔍",
    layout="wide"
)

st.title("🔍 GenBI - 生成式BI查询系统")
st.markdown("基于大模型的智能数据库查询和分析平台")

# 侧边栏导航
st.sidebar.title("导航")
pages = {
    "LLM配置": "pages/llm_config.py",
    "数据库配置": "pages/database_config.py", 
    "Schema配置": "pages/schema_config.py",
    "智能聊天": "pages/chat.py",
    "MCP管理": "pages/mcp_management.py",
    "API文档": "pages/api_docs.py"
}

# 主页内容
st.markdown("""
## 功能特性

- 🤖 **智能查询**: 自然语言转SQL查询
- 📊 **数据分析**: AI驱动的数据洞察
- 🔗 **多数据源**: 支持AWS Athena和MySQL
- 🛠️ **MCP集成**: 可扩展的工具生态
- 📋 **API接口**: 完整的RESTful API

## 快速开始

1. 配置LLM服务 → LLM配置
2. 连接数据库 → 数据库配置  
3. 设置表结构 → Schema配置
4. 开始智能查询 → 智能聊天

请从左侧导航开始配置系统。
""")