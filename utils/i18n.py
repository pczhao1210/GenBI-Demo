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
        
        # Timeout configuration
        "timeout_config": "超时配置",
        "timeout_config_help": "配置不同类型请求的超时时间，提高系统稳定性",
        "timeout_mode": "超时模式",
        "timeout_mode_help": "选择超时配置模式：自动智能、全局统一、或按意图分类",
        "auto_timeout_description": "系统将根据意图智能设置超时时间（查询意图70秒，分析意图240秒）",
        "global_timeout_seconds": "全局超时时间（秒）",
        "global_timeout_help": "所有请求使用统一的超时时间",
        "intent_timeout_settings": "按意图分类超时设置",
        "query_intent_timeout": "查询意图（秒）",
        "query_intent_help": "SQL查询生成、数据检索等查询类操作的超时时间",
        "analysis_intent_timeout": "分析意图（秒）",
        "analysis_intent_help": "意图识别、分析计划生成、复杂分析等分析类操作的超时时间",
        "default_timeout": "默认超时（秒）",
        "default_timeout_help": "未分类请求的默认超时时间",
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
        
        # Timeout configuration
        "timeout_config": "Timeout Configuration",
        "timeout_config_help": "Configure timeout settings for different types of requests to improve system stability",
        "timeout_mode": "Timeout Mode",
        "timeout_mode_help": "Choose timeout configuration mode: Auto intelligence, Global unified, or Intent classified",
        "auto_timeout_description": "System will intelligently set timeout based on intent (Query intent 70s, Analysis intent 240s)",
        "global_timeout_seconds": "Global Timeout (seconds)",
        "global_timeout_help": "Use unified timeout for all requests",
        "intent_timeout_settings": "Intent-Based Timeout Settings",
        "query_intent_timeout": "Query Intent (seconds)",
        "query_intent_help": "Timeout for SQL query generation, data retrieval and other query operations",
        "analysis_intent_timeout": "Analysis Intent (seconds)",
        "analysis_intent_help": "Timeout for intent recognition, analysis plan generation and complex analysis operations",
        "default_timeout": "Default Timeout (seconds)",
        "default_timeout_help": "Default timeout for unclassified requests",
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

TRANSLATIONS["zh"].update({
    "readonly_notice": "仅支持只读查询；SQL 校验始终启用，请使用数据库只读账号。",
    "result_truncated": "结果已达到返回行数上限，请勿将其视为完整数据。",
    "analysis_plan": "分析计划",
    "execute_plan": "执行计划",
    "cancel_plan": "取消计划",
    "retry_plan": "重新执行上次未完成的计划",
    "plan_updated": "计划已更新，可继续补充、执行或取消。",
    "plan_ready": "计划已生成，请确认后执行；也可以输入修改意见。",
    "execution_failed": "执行失败",
    "enable_on_demand": "启用按需调用",
    "disable_server": "禁用调用",
})
TRANSLATIONS["en"].update({
    "readonly_notice": "Read-only queries only. SQL validation is always enabled; use a read-only database account.",
    "result_truncated": "The row limit was reached. This is not the complete dataset.",
    "analysis_plan": "Analysis plan",
    "execute_plan": "Execute plan",
    "cancel_plan": "Cancel plan",
    "retry_plan": "Rerun the last incomplete plan",
    "plan_updated": "Plan updated. You can revise, execute, or cancel it.",
    "plan_ready": "Plan ready. Review it before execution or enter feedback.",
    "execution_failed": "Execution failed",
    "enable_on_demand": "Enable on-demand calls",
    "disable_server": "Disable calls",
})
for key, zh, en in [
    ("search_fields", "检索字段与描述", "Search fields and descriptions"), ("preview_data", "预览有限行数据", "Preview limited rows"),
    ("batch_descriptions", "批量编辑描述与业务键", "Batch edit descriptions and business keys"),
    ("apply_descriptions", "应用批量编辑", "Apply batch edits"), ("schema_diff", "字段差异（新增 / 移除）", "Column differences (added / removed)"),
    ("start_page", "开始", "Start"), ("workspace_nav", "分析工作区", "Workspace"),
    ("configuration_nav", "配置与知识", "Configuration & knowledge"), ("developer_nav", "开发入口", "Developer"),
    ("welcome_description", "理解业务问题，取得可复核的数据，展示结论和证据边界。", "Understand questions, obtain verifiable data, and show conclusions with evidence limits."),
    ("setup_wizard", "配置向导", "Setup wizard"), ("configured", "已配置", "Configured"),
    ("needs_configuration", "待配置", "Needs configuration"), ("configure_now", "前往配置", "Configure"),
    ("configured_not_connected", "以下状态仅表示配置已保存，不代表真实连接测试通过。术语解释与样例回放可独立使用。",
     "Readiness means saved configuration, not a verified live connection. Concept help and sample replay are independent."),
    ("start_analysis", "开始分析", "Start analysis"), ("try_sample_replay", "体验样例回放", "Try sample replay"),
    ("recent_runs", "最近任务", "Recent runs"), ("open_run", "查看任务", "Open run"),
    ("demo_scenarios", "演示场景", "Demo scenarios"), ("prerequisites", "先决条件", "Prerequisites"),
    ("missing_prerequisites", "尚缺配置", "Missing configuration"), ("use_scenario", "使用此问题", "Use question"),
    ("sample_replay", "样例回放（非实时）", "Sample replay (not live)"),
    ("result_view", "结果视图", "Result view"), ("table_view", "表格", "Table"), ("chart_view", "图表", "Chart"),
    ("chart_precision", "图表使用近似数值展示；精确值、NULL 与单位请以表格和 JSON 为准。",
     "Charts use approximate numeric values; tables and JSON retain exact values, NULLs and units."),
    ("result_scope", "口径、时间、覆盖与计算校验", "Definitions, time, coverage and computation checks"),
    ("download_csv", "导出表格 CSV", "Export table CSV"), ("empty_result", "查询成功，但当前条件下没有数据。", "Query succeeded with no rows matching the conditions."),
    ("evidence_sources", "支持证据与来源", "Evidence and sources"), ("open_source", "打开来源", "Open source"),
    ("conversation_history", "会话历史", "Conversation history"), ("dependencies", "依赖", "Dependencies"),
    ("plan_feedback", "计划修改意见（不会作为新问题执行）", "Plan feedback (not a new question)"),
    ("revise_plan", "修改此计划", "Revise this plan"), ("historical_result", "历史运行结果", "Historical result"),
    ("refresh_analysis", "刷新分析（新运行）", "Refresh analysis (new run)"), ("download_run", "导出运行与证据 JSON", "Export run and evidence JSON"),
    ("active_sources", "活动数据源集合", "Active data sources"),
    ("standard_mcp_config", "标准 MCP 服务器配置", "Standard MCP server configuration"),
    ("standard_mcp_help", "按服务器名称填写 JSON：protocol=mcp，type=stdio 或 streamable_http，status=active，capabilities 为能力到工具名的映射。内置工具无需改写。",
     "JSON keyed by server: protocol=mcp, type=stdio or streamable_http, status=active, capabilities maps capabilities to tool names. Built-in tools are unchanged."),
    ("standard_mcp_json", "MCP JSON", "MCP JSON"), ("save_standard_mcp", "保存 MCP 服务器", "Save MCP servers"),
    ("methods_title", "方法与验证案例", "Methods and validated cases"),
    ("methods_help", "方法需依次经过 draft / validated / published。验证阶段填写 reviewer、fixture_ids、passed；仅发布的方法参与检索，历史源与结论不进入新计划。",
     "Move methods through draft / validated / published with reviewer, fixture_ids and passed validation. Only published methods are retrieved; historical bindings and conclusions are excluded."),
    ("methods_json", "方法库 JSON", "Method library JSON"), ("save_methods", "保存方法库", "Save method library"),
    ("analysis_ledger", "任务与进度账本", "Task and progress ledger"),
    ("semantics_title", "业务语义与知识", "Business semantics & knowledge"),
    ("ontology_title", "可计算语义", "Computable ontology"), ("knowledge_title", "知识资料", "Knowledge"),
    ("ontology_help", "指标需填写 formula、aggregation、time_field、unit、allowed_dimensions、mappings。无映射表示可解释但不可计算。",
     "Metrics require formula, aggregation, time_field, unit, allowed_dimensions and mappings. No mapping means explainable, not computable."),
    ("ontology_json", "Ontology JSON", "Ontology JSON"), ("save_ontology", "保存语义定义", "Save ontology"),
    ("index_status", "已索引片段", "Indexed chunks"), ("document_title", "文档标题", "Document title"),
    ("document_source", "来源 URL / 文档 ID", "Source URL / document ID"), ("document_version", "版本", "Version"),
    ("document_scope", "适用范围（* 为通用）", "Scope (* for general)"), ("document_text", "正文", "Text"),
    ("import_document", "导入 UTF-8 文档", "Import UTF-8 document"), ("add_document", "保存并索引", "Save and index"),
    ("retrieval_test", "检索试验", "Test retrieval"), ("model_roles_title", "节点模型角色", "Node model roles"),
    ("model_roles_help", "fast / sql / reasoning 各填完整模型配置；未覆盖的角色明确共用主配置，不自动降级。",
     "Provide complete configurations for fast / sql / reasoning. Unmapped roles share the main configuration; no silent fallback."),
    ("model_roles_json", "角色配置 JSON", "Role configuration JSON"), ("save_model_roles", "保存模型角色", "Save model roles"),
    ("understood_question", "我理解的问题与继承条件", "Understood question and inherited conditions"),
    ("answer_sufficiency", "回答充分性", "Answer sufficiency"),
    ("source_connection", "连接", "Connection"), ("new_connection", "新增连接", "New connection"),
    ("connection_name", "连接名称", "Connection name"), ("host", "主机", "Host"),
    ("database", "数据库", "Database"), ("username", "用户名", "Username"),
    ("password", "密码", "Password"), ("port", "端口", "Port"), ("schema_name", "Schema", "Schema"),
    ("business_timezone", "业务时区", "Business timezone"), ("business_day_hour", "业务日起始小时", "Business day start hour"),
    ("row_limit", "最大返回行数", "Maximum rows"), ("query_timeout_label", "查询超时（秒）", "Query timeout (seconds)"),
    ("test_source", "🔍 测试连接", "Test connection"), ("save_source", "💾 保存配置", "Save connection"),
    ("source_diagnostics", "能力与驱动诊断", "Capabilities and driver diagnostics"),
    ("odbc_driver", "系统 ODBC 驱动", "System ODBC driver"), ("encrypt", "加密", "Encrypt"),
    ("trust_certificate", "信任服务端证书", "Trust server certificate"),
    ("odbc_notice", "MSSQL 需要系统安装 Microsoft ODBC Driver 18 和 unixODBC；Python 包不包含系统驱动。",
     "MSSQL requires Microsoft ODBC Driver 18 and unixODBC installed on the host, not just the Python package."),
    ("ssl_mode_label", "SSL 模式", "SSL mode"),
    ("configure_source_hint", "请先在数据源页面添加连接；知识解释无需连接。", "Add a data source first; knowledge explanations do not require a connection."),
]:
    TRANSLATIONS["zh"][key], TRANSLATIONS["en"][key] = zh, en


TRANSLATIONS["zh"].update({
    "new_conversation": "新建会话", "completed_steps": "已完成步骤",
    "debug_details": "调试详情", "additional_input": "补充信息",
    "submit_response": "提交回复", "resume_run": "恢复中断任务",
    "run_events": "运行事件 / 历史回放",
    "cooperative_cancel": "取消将停止后续调度；在途工具结束前保持取消中，不宣称已中断数据库。",
})
TRANSLATIONS["en"].update({
    "new_conversation": "New conversation", "completed_steps": "Completed steps",
    "debug_details": "Debug details", "additional_input": "Additional information",
    "submit_response": "Submit response", "resume_run": "Resume interrupted run",
    "run_events": "Run events / replay",
    "cooperative_cancel": "Cancellation stops scheduling; in-flight tools must finish before cancellation is confirmed.",
})


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
    
    def changed():
        set_language(lang_options[st.session_state.language_selector])

    st.selectbox(
        "Language / 语言",
        options=list(lang_options.keys()),
        index=list(lang_options.values()).index(current_lang),
        key="language_selector",
        on_change=changed,
    )