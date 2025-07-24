import streamlit as st
import sys

# Language translations
TRANSLATIONS = {
    "zh": {
        # Main app
        "app_title": "GenBI - 生成式BI查询系统",
        "app_subtitle": "基于大模型的智能数据库查询和分析平台",
        "navigation": "导航",
        "features": "功能特性",
        "quick_start": "快速开始",
        "feature_smart_query": "🤖 **智能查询**: 自然语言转SQL查询",
        "feature_data_analysis": "📊 **数据分析**: AI驱动的数据洞察",
        "feature_multi_source": "🔗 **多数据源**: 支持AWS Athena和MySQL",
        "feature_mcp": "🛠️ **MCP集成**: 可扩展的工具生态",
        "feature_api": "📋 **API接口**: 完整的RESTful API",
        "quick_start_content": """
1. 配置LLM服务 → LLM配置
2. 连接数据库 → 数据库配置  
3. 设置表结构 → Schema配置
4. 开始智能查询 → 智能聊天

请从左侧导航开始配置系统。
        """,
        
        # Navigation
        "llm_config": "LLM配置",
        "database_config": "数据库配置",
        "schema_config": "Schema配置",
        "smart_chat": "智能聊天",
        "mcp_management": "MCP管理",
        "api_docs": "API文档",
        
        # Common
        "save_config": "保存配置",
        "test_connection": "测试连接",
        "config_saved": "配置已保存！",
        "connection_test_success": "连接测试成功！",
        "connection_test_failed": "连接测试失败",
        "select_provider": "选择LLM提供商",
        "config_params": "配置参数",
        "model_params": "模型参数",
        "language": "语言",
        "testing_connection": "测试连接中...",
        "response_time": "响应时间",
        "model_response": "模型响应:",
        "response_content": "响应内容",
        "connection_success_unexpected": "连接成功，但模型响应不符合预期",
        "check_config": "请检查您的配置参数并重试",
        "select_database_type": "选择数据库类型",
        "max_rows": "最大返回行数",
        "use_s3_output": "使用S3输出位置",
        
        # API Docs
        "service_status": "🔍 服务状态",
        "api_endpoints": "📋 API端点",
        "detailed_docs": "📖 详细文档",
        "new_features": "✨ 新增功能",
        "api_testing": "🧪 API测试",
        "quick_test_api": "快速测试API",
        "select_endpoint": "选择端点",
        "input_query": "输入查询问题",
        "database_type": "数据库类型",
        "generate_sql": "生成SQL",
        "test_connection_btn": "测试连接",
        "api_error": "API错误",
        "connection_failed": "连接失败",
        
        # Chat
        "smart_chat": "💬 智能聊天",
        "settings": "设置",
        "select_database": "选择数据库",
        "llm_model_settings": "LLM模型设置",
        "llm_provider": "LLM提供商",
        "model": "模型",
        "current_using": "当前使用",
        "display_settings": "显示设置",
        "show_schema_prompt": "显示Schema提示",
        "use_llm_generate_sql": "使用LLM生成SQL",
        "security_settings": "安全设置",
        "avoid_dangerous_code": "避免执行危险代码",
        "enter_question": "请输入您的问题...",
        "thinking": "思考中...",
        "clear_history": "清除历史",
        
        # MCP Management
        "mcp_tool_management": "🔧 MCP工具管理",
        "add_mcp_server": "添加MCP Server",
        "new_server": "新增服务器",
        "server_name": "服务器名称",
        "type": "类型",
        "command": "命令",
        "parameters": "参数",
        "add_server": "添加服务器",
        "mcp_server_list": "MCP Server列表",
        "no_mcp_servers": "暂无MCP服务器，请添加新的服务器",
        "start": "启动",
        "stop": "停止",
        "delete": "删除",
        "started": "已启动",
        "stopped": "已停止",
        "deleted": "已删除",
        
        # Schema Config
        "database_schema_config": "📋 数据库Schema配置",
        "table_list": "表列表",
        "refresh_schema": "刷新Schema",
        "select_table": "选择表",
        "click_refresh_schema": "点击'刷新Schema'获取表列表",
        "table_details": "表详情",
        "table_description": "表描述",
        "get_field_info": "获取字段信息",
        "field_list": "字段列表",
        "custom_description": "自定义描述",
        "click_get_field_info": "点击'获取字段信息'查看表结构",
        "select_table_first": "请先选择一个表",
        "show_saved_schema": "显示已保存的Schema配置",
        "no_saved_config": "暂无已保存的配置",
        "config_db_connection_first": "请先在数据库配置页面配置{db_type}连接信息",
        "config_schema_first": "未找到{db_type}的Schema配置，请先在Schema配置页面配置表结构",
        
        # API Docs additional
        "running": "🟢 运行中",
        "offline": "🔴 离线",
        "normal": "🟢 正常",
        "abnormal": "🟡 异常",
        "api_service": "API服务",
        "execute_data_query": "执行数据查询",
        "execute_data_analysis": "执行数据分析",
        "optimize_analysis_chain": "优化分析链",
        "generate_sql_statement": "生成SQL查询语句（系统集成）",
        "service_health_check": "服务健康检查",
        "swagger_ui_docs": "🔗 Swagger UI文档",
        "api_test_tool": "🧪 API测试工具",
        "open_in_new_tab": "在新标签页中打开",
        "sql_generation_api": "SQL生成API",
        "function": "功能",
        "generate_sql_from_nl": "根据自然语言问题生成SQL查询语句",
        "request_example": "请求示例",
        "response_example": "响应示例",
        "use_cases": "使用场景",
        "system_integration_automation": "系统集成、自动化查询生成",
        "test_sql_generation_api": "测试SQL生成API",
        "api_service_normal": "API服务正常",
        
        # LLM Config additional
        "openai_config": "OpenAI配置",
        "azure_openai_config": "Azure OpenAI配置",
        "custom_config": "自定义配置",
        "model_name": "模型名称",
        "db_config_header": "{db_type}配置",
    },
    "en": {
        # Main app
        "app_title": "GenBI - Generative BI Query System",
        "app_subtitle": "Intelligent database query and analysis platform based on large language models",
        "navigation": "Navigation",
        "features": "Features",
        "quick_start": "Quick Start",
        "feature_smart_query": "🤖 **Smart Query**: Natural language to SQL query conversion",
        "feature_data_analysis": "📊 **Data Analysis**: AI-driven data insights",
        "feature_multi_source": "🔗 **Multi-Data Sources**: Support for AWS Athena and MySQL",
        "feature_mcp": "🛠️ **MCP Integration**: Extensible tool ecosystem",
        "feature_api": "📋 **API Interface**: Complete RESTful API",
        "quick_start_content": """
1. Configure LLM Service → LLM Configuration
2. Connect Database → Database Configuration  
3. Set Table Structure → Schema Configuration
4. Start Smart Query → Smart Chat

Please start configuring the system from the left navigation.
        """,
        
        # Navigation
        "llm_config": "LLM Configuration",
        "database_config": "Database Configuration",
        "schema_config": "Schema Configuration",
        "smart_chat": "Smart Chat",
        "mcp_management": "MCP Management",
        "api_docs": "API Documentation",
        
        # Common
        "save_config": "Save Configuration",
        "test_connection": "Test Connection",
        "config_saved": "Configuration saved!",
        "connection_test_success": "Connection test successful!",
        "connection_test_failed": "Connection test failed",
        "select_provider": "Select LLM Provider",
        "config_params": "Configuration Parameters",
        "model_params": "Model Parameters",
        "language": "Language",
        "testing_connection": "Testing connection...",
        "response_time": "Response time",
        "model_response": "Model response:",
        "response_content": "Response content",
        "connection_success_unexpected": "Connection successful, but model response is unexpected",
        "check_config": "Please check your configuration parameters and try again",
        "select_database_type": "Select Database Type",
        "max_rows": "Maximum Rows",
        "use_s3_output": "Use S3 Output Location",
        
        # API Docs
        "service_status": "🔍 Service Status",
        "api_endpoints": "📋 API Endpoints",
        "detailed_docs": "📖 Detailed Documentation",
        "new_features": "✨ New Features",
        "api_testing": "🧪 API Testing",
        "quick_test_api": "Quick Test API",
        "select_endpoint": "Select Endpoint",
        "input_query": "Input Query Question",
        "database_type": "Database Type",
        "generate_sql": "Generate SQL",
        "test_connection_btn": "Test Connection",
        "api_error": "API Error",
        "connection_failed": "Connection Failed",
        
        # Chat
        "smart_chat": "💬 Smart Chat",
        "settings": "Settings",
        "select_database": "Select Database",
        "llm_model_settings": "LLM Model Settings",
        "llm_provider": "LLM Provider",
        "model": "Model",
        "current_using": "Currently Using",
        "display_settings": "Display Settings",
        "show_schema_prompt": "Show Schema Prompt",
        "use_llm_generate_sql": "Use LLM to Generate SQL",
        "security_settings": "Security Settings",
        "avoid_dangerous_code": "Avoid Executing Dangerous Code",
        "enter_question": "Please enter your question...",
        "thinking": "Thinking...",
        "clear_history": "Clear History",
        
        # MCP Management
        "mcp_tool_management": "🔧 MCP Tool Management",
        "add_mcp_server": "Add MCP Server",
        "new_server": "New Server",
        "server_name": "Server Name",
        "type": "Type",
        "command": "Command",
        "parameters": "Parameters",
        "add_server": "Add Server",
        "mcp_server_list": "MCP Server List",
        "no_mcp_servers": "No MCP servers available, please add a new server",
        "start": "Start",
        "stop": "Stop",
        "delete": "Delete",
        "started": "Started",
        "stopped": "Stopped",
        "deleted": "Deleted",
        
        # Schema Config
        "database_schema_config": "📋 Database Schema Configuration",
        "table_list": "Table List",
        "refresh_schema": "Refresh Schema",
        "select_table": "Select Table",
        "click_refresh_schema": "Click 'Refresh Schema' to get table list",
        "table_details": "Table Details",
        "table_description": "Table Description",
        "get_field_info": "Get Field Information",
        "field_list": "Field List",
        "custom_description": "Custom Description",
        "click_get_field_info": "Click 'Get Field Information' to view table structure",
        "select_table_first": "Please select a table first",
        "show_saved_schema": "Show Saved Schema Configuration",
        "no_saved_config": "No saved configuration available",
        "config_db_connection_first": "Please configure {db_type} connection information in the database configuration page first",
        "config_schema_first": "No Schema configuration found for {db_type}, please configure table structure in Schema configuration page first",
        
        # API Docs additional
        "running": "🟢 Running",
        "offline": "🔴 Offline",
        "normal": "🟢 Normal",
        "abnormal": "🟡 Abnormal",
        "api_service": "API Service",
        "execute_data_query": "Execute data query",
        "execute_data_analysis": "Execute data analysis",
        "optimize_analysis_chain": "Optimize analysis chain",
        "generate_sql_statement": "Generate SQL query statement (system integration)",
        "service_health_check": "Service health check",
        "swagger_ui_docs": "🔗 Swagger UI Documentation",
        "api_test_tool": "🧪 API Test Tool",
        "open_in_new_tab": "Open in new tab",
        "sql_generation_api": "SQL Generation API",
        "function": "Function",
        "generate_sql_from_nl": "Generate SQL query statements from natural language questions",
        "request_example": "Request Example",
        "response_example": "Response Example",
        "use_cases": "Use Cases",
        "system_integration_automation": "System integration, automated query generation",
        "test_sql_generation_api": "Test SQL Generation API",
        "api_service_normal": "API service normal",
        
        # LLM Config additional
        "openai_config": "OpenAI Configuration",
        "azure_openai_config": "Azure OpenAI Configuration",
        "custom_config": "Custom Configuration",
        "model_name": "Model Name",
        "db_config_header": "{db_type} Configuration",
    }
}

def get_language():
    """Get current language from session state"""
    # Check for command line argument first
    if 'language' not in st.session_state:
        default_lang = 'zh'
        for arg in sys.argv:
            if arg.startswith('--language='):
                lang_arg = arg.split('=')[1].lower()
                if lang_arg in ['english', 'en']:
                    default_lang = 'en'
                break
        st.session_state.language = default_lang
    return st.session_state.get('language', 'zh')

def set_language(lang):
    """Set language in session state"""
    st.session_state.language = lang

def t(key, default=None):
    """Get translation for key"""
    lang = get_language()
    return TRANSLATIONS.get(lang, {}).get(key, default or key)

def language_selector():
    """Language selector widget"""
    current_lang = get_language()
    lang_options = {"中文": "zh", "English": "en"}
    
    # Show opposite language as label
    label = "Language" if current_lang == "zh" else "语言"
    
    selected = st.selectbox(
        label,
        options=list(lang_options.keys()),
        index=0 if current_lang == "zh" else 1,
        key="language_selector"
    )
    
    new_lang = lang_options[selected]
    if new_lang != current_lang:
        set_language(new_lang)
        st.rerun()