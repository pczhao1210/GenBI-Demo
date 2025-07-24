import streamlit as st
import pandas as pd
import re
from utils.mcp_client import MCPClient
from utils.config_manager import ConfigManager
from utils.llm_client import LLMClient

st.set_page_config(page_title="智能聊天", page_icon="💬", layout="wide")
st.title("💬 智能聊天")

# 初始化客户端和配置管理器
mcp_client = MCPClient()
config_manager = ConfigManager()

# 初始化聊天历史和分析状态
if "messages" not in st.session_state:
    st.session_state.messages = []
if "analysis_plan" not in st.session_state:
    st.session_state.analysis_plan = None
if "analysis_question" not in st.session_state:
    st.session_state.analysis_question = None

# 创建边栏
with st.sidebar:
    st.header("设置")
    
    # 数据库选择
    database_type = st.selectbox("选择数据库", ["mysql", "athena"])
    
    # 加载数据库配置
    db_config = config_manager.load_database_config().get(database_type, {})
    if not db_config:
        st.warning(f"请先在数据库配置页面配置{database_type.upper()}连接信息")
    
    # 加载LLM配置
    llm_config = config_manager.load_llm_config()
    
    # LLM模型选择
    st.subheader("LLM模型设置")
    provider = st.selectbox(
        "LLM提供商",
        ["openai", "azure_openai", "custom"],
        index=["openai", "azure_openai", "custom"].index(llm_config.get("provider", "openai"))
    )
    
    # 显示当前选择的模型
    if provider == "openai":
        model = st.selectbox(
            "模型",
            ["gpt-4", "gpt-3.5-turbo", "gpt-4-turbo"],
            index=["gpt-4", "gpt-3.5-turbo", "gpt-4-turbo"].index(llm_config.get("openai", {}).get("model", "gpt-4"))
        )
        st.info(f"当前使用: OpenAI - {model}")
    elif provider == "azure_openai":
        deployment = llm_config.get("azure_openai", {}).get("deployment_name", "")
        st.info(f"当前使用: Azure OpenAI - {deployment}")
    else:  # custom
        model = llm_config.get("custom", {}).get("model", "llama2")
        st.info(f"当前使用: 自定义 - {model}")
    
    # 其他设置
    st.subheader("显示设置")
    show_schema = st.checkbox("显示Schema提示", value=True)
    use_llm = st.checkbox("使用LLM生成SQL", value=True)
    
    st.subheader("安全设置")
    check_dangerous_sql = st.checkbox("避免执行危险代码", value=True)
    
    # 初始化LLM客户端
    llm_client = LLMClient(llm_config)

# 显示聊天历史
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "data" in message:
            st.dataframe(message["data"])

# 获取保存的表结构信息
def get_saved_schema(config_manager, database_type):
    schema_config = config_manager.load_schema_config().get(database_type, {})
    return schema_config.get("tables", {}), schema_config.get("descriptions", {})

# 构建包含schema的prompt
def build_schema_prompt(question, schema_info, table_descriptions):
    prompt = f"""### 数据库查询

用户问题: {question}

### 数据库Schema:
"""
    
    for table, columns in schema_info.items():
        table_desc = table_descriptions.get(table, "")
        prompt += f"\n\n表: {table}"
        if table_desc:
            prompt += f" - {table_desc}"
        prompt += "\n"
        
        if columns:
            prompt += "| 列名 | 类型 | 描述 |\n"
            prompt += "| --- | --- | --- |\n"
            for col in columns:
                name = col.get("name", "")
                col_type = col.get("type", "")
                comment = col.get("comment", "")
                prompt += f"| {name} | {col_type} | {comment} |\n"
        else:
            prompt += "表结构信息未配置\n"
    
    prompt += "\n\n请根据用户问题和数据库schema生成SQL查询。"
    
    return prompt

# 使用LLM进行意图识别
def identify_intent_with_llm(question, llm_client):
    intent_prompt = f"""请分析以下用户问题的意图，只返回下列之一：
- query: 查询数据
- analysis: 数据分析
- reject: 涉及数据库增删改操作（INSERT/UPDATE/DELETE/DROP/CREATE/ALTER等）

用户问题: {question}

意图:"""
    
    try:
        response = llm_client.generate_sql(intent_prompt)
        if response:
            response_lower = response.lower().strip()
            if "reject" in response_lower:
                return "reject"
            elif "analysis" in response_lower:
                return "analysis"
            else:
                return "query"
    except:
        pass
    
    return "query"  # 默认返回查询

# 生成分析思路
def generate_analysis_plan(question, schema_info, table_descriptions, llm_client):
    plan_prompt = f"""请为以下数据分析问题制定详细的分析思路和步骤：

用户问题: {question}

数据库表结构:
"""
    
    for table, columns in schema_info.items():
        table_desc = table_descriptions.get(table, "")
        plan_prompt += f"\n表: {table}"
        if table_desc:
            plan_prompt += f" - {table_desc}"
        plan_prompt += "\n"
        
        if columns:
            for col in columns:
                name = col.get("name", "")
                col_type = col.get("type", "")
                comment = col.get("comment", "")
                plan_prompt += f"  - {name} ({col_type}): {comment}\n"
    
    plan_prompt += "\n\n请提供一个分步骤的分析计划，包括：\n1. 分析目标\n2. 所需数据\n3. 分析步骤\n4. 预期结果"
    
    try:
        response = llm_client.generate_sql(plan_prompt)
        return response
    except Exception as e:
        return f"生成分析计划时出错: {str(e)}"

# 使用LLM检测是否为执行意图
def is_execute_intent_with_llm(question, llm_client):
    execute_prompt = f"""请分析以下用户输入是否表示要执行当前的分析计划：

用户输入: {question}

请只返回：
- execute: 用户要求执行分析计划
- modify: 用户要求修改或补充计划

意图:"""
    
    try:
        response = llm_client.generate_sql(execute_prompt)
        if response and "execute" in response.lower():
            return True
    except:
        pass
    
    return False

# 检测SQL中的危险操作
def check_dangerous_sql_operations(sql):
    dangerous_keywords = [
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 
        'TRUNCATE', 'REPLACE', 'MERGE', 'GRANT', 'REVOKE'
    ]
    
    sql_upper = sql.upper().strip()
    for keyword in dangerous_keywords:
        if keyword in sql_upper:
            return True, keyword
    return False, None

# SQL生成函数
def generate_sql(question, database_type, config_manager, llm_client=None, use_llm=False):
    # 获取保存的schema信息
    schema_info, table_descriptions = get_saved_schema(config_manager, database_type)
    
    # 构建包含schema的prompt
    schema_prompt = build_schema_prompt(question, schema_info, table_descriptions)
    
    # 使用LLM生成SQL
    sql = ""
    if use_llm and llm_client:
        try:
            # 调用LLM API生成SQL
            llm_response = llm_client.generate_sql(schema_prompt)
            if llm_response:
                # 从响应中提取SQL
                sql_match = re.search(r'```sql\s*([\s\S]*?)\s*```', llm_response)
                if sql_match:
                    sql = sql_match.group(1).strip()
                else:
                    # 尝试其他SQL代码块格式
                    sql_match = re.search(r'```\s*([\s\S]*?)\s*```', llm_response)
                    if sql_match:
                        sql = sql_match.group(1).strip()
                    else:
                        # 如果没有SQL代码块，尝试直接提取
                        sql = llm_response.strip()
        except Exception as e:
            print(f"LLM生成SQL时出错: {str(e)}")
    
    # 如果没有使用LLM或LLM生成失败，使用规则生成SQL
    if not sql:
        tables = list(schema_info.keys())
        for table in tables:
            if table.lower() in question.lower():
                sql = f"SELECT * FROM {table} LIMIT 10"
                break
        
        if not sql and ("查询" in question or "显示" in question or "select" in question.lower()):
            if tables:
                sql = f"SELECT * FROM {tables[0]} LIMIT 10"
    
    # 返回生成的SQL和包含schema的prompt
    return sql, schema_prompt

# 聊天输入
if prompt := st.chat_input("请输入您的问题..."):
    # 添加用户消息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 生成助手回复
    with st.chat_message("assistant"):
        with st.spinner("思考中..."):
            if not db_config:
                response = "请先在数据库配置页面配置数据库连接信息"
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
            else:
                # 检查是否有保存的schema
                schema_info, table_descriptions = get_saved_schema(config_manager, database_type)
                
                if not schema_info:
                    response = f"未找到{database_type.upper()}的Schema配置，请先在Schema配置页面配置表结构"
                    st.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                else:
                    # 检查是否在分析计划阶段
                    if st.session_state.analysis_plan:
                        # 在分析计划阶段，检测是否为执行意图
                        if use_llm and llm_client and is_execute_intent_with_llm(prompt, llm_client):
                            intent = "analysis_execute"
                        else:
                            intent = "analysis_modify"
                    else:
                        # 正常意图识别
                        if use_llm and llm_client:
                            intent = identify_intent_with_llm(prompt, llm_client)
                        else:
                            intent = "query"
                    
                    intent_map = {
                        "query": "查询意图",
                        "analysis": "分析意图",
                        "analysis_execute": "分析意图 - 执行阶段",
                        "analysis_modify": "分析意图 - 修改阶段",
                        "reject": "拒绝意图"
                    }
                    
                    # 如果是拒绝意图，直接返回拒绝信息
                    if intent == "reject":
                        response = f"[意图识别] 拒绝意图\n\n抱歉，为了数据安全，系统不支持数据库的增删改操作。\n只支持数据查询和分析功能。"
                        st.markdown(response)
                        st.session_state.messages.append({"role": "assistant", "content": response})
                    elif intent == "analysis_execute":
                        # 执行分析计划
                            # 执行分析计划
                            sql, schema_prompt = generate_sql(st.session_state.analysis_question, database_type, config_manager, llm_client, use_llm)
                            
                            if sql:
                                # 检测危险SQL操作
                                if check_dangerous_sql:
                                    is_dangerous, dangerous_keyword = check_dangerous_sql_operations(sql)
                                    if is_dangerous:
                                        response = f"[安全检测] 检测到危险操作\n\n检测到SQL中包含危险操作: {dangerous_keyword}\n为了数据安全，系统拒绝执行此查询。\n\n生成的SQL:\n```sql\n{sql}\n```"
                                        st.markdown(response)
                                        st.session_state.messages.append({"role": "assistant", "content": response})
                                        st.stop()
                                
                                # 执行分析查询
                                response_parts = []
                                response_parts.append(f"[意图识别] 分析意图 - 执行阶段")
                                response_parts.append(f"正在执行分析: {st.session_state.analysis_question}")
                                response_parts.append(f"数据库: {database_type}")
                                response_parts.append(f"SQL: \n```sql\n{sql}\n```")
                                
                                response = "\n\n".join(response_parts)
                                st.markdown(response)
                                
                                # 执行查询
                                with st.spinner("执行分析查询中..."):
                                    query_result = mcp_client.call_mcp_server_with_config(
                                        database_type,
                                        "execute_query",
                                        db_config,
                                        {"sql": sql, "database": db_config.get("database")}
                                    )
                                    
                                    if "error" in query_result:
                                        st.error(f"查询失败: {query_result['error']}")
                                        st.session_state.messages.append({"role": "assistant", "content": response + "\n\n查询失败: " + query_result['error']})
                                    elif "result" in query_result and "data" in query_result["result"]:
                                        columns = query_result["result"]["data"].get("columns", [])
                                        rows = query_result["result"]["data"].get("rows", [])
                                        
                                        if rows:
                                            df = pd.DataFrame(rows, columns=columns)
                                            st.dataframe(df)
                                            st.session_state.messages.append({
                                                "role": "assistant", 
                                                "content": response,
                                                "data": df
                                            })
                                        else:
                                            st.info("查询结果为空")
                                            st.session_state.messages.append({"role": "assistant", "content": response + "\n\n查询结果为空"})
                                    else:
                                        st.warning("查询结果格式不正确")
                                        st.session_state.messages.append({"role": "assistant", "content": response + "\n\n查询结果格式不正确"})
                                
                                # 清除分析计划
                                st.session_state.analysis_plan = None
                                st.session_state.analysis_question = None
                            else:
                                response = "无法生成分析SQL查询"
                                st.markdown(response)
                                st.session_state.messages.append({"role": "assistant", "content": response})
                    elif intent == "analysis_modify":
                        # 修改分析计划
                        if use_llm and llm_client:
                            # 更新分析计划
                            updated_plan = generate_analysis_plan(f"{st.session_state.analysis_question}\n\n用户补充: {prompt}", schema_info, table_descriptions, llm_client)
                            st.session_state.analysis_plan = updated_plan
                            
                            response = f"[意图识别] 分析意图 - 修改阶段\n\n已根据您的补充更新分析计划：\n\n{updated_plan}\n\n---\n\n请输入“执行”或类似意思来开始分析。"
                            st.markdown(response)
                            st.session_state.messages.append({"role": "assistant", "content": response})
                        else:
                            response = "请先启用LLM功能才能进行数据分析"
                            st.markdown(response)
                            st.session_state.messages.append({"role": "assistant", "content": response})
                    elif intent == "analysis":
                        # 生成分析计划
                        if use_llm and llm_client:
                            analysis_plan = generate_analysis_plan(prompt, schema_info, table_descriptions, llm_client)
                            st.session_state.analysis_plan = analysis_plan
                            st.session_state.analysis_question = prompt
                            
                            response = f"[意图识别] 分析意图 - 计划阶段\n\n以下是为您的分析问题制定的计划：\n\n{analysis_plan}\n\n---\n\n请输入“执行”或类似意思来开始分析。"
                            st.markdown(response)
                            st.session_state.messages.append({"role": "assistant", "content": response})
                        else:
                            response = "请先启用LLM功能才能进行数据分析"
                            st.markdown(response)
                            st.session_state.messages.append({"role": "assistant", "content": response})
                    else:
                        # 生成SQL查询
                        sql, schema_prompt = generate_sql(prompt, database_type, config_manager, llm_client, use_llm)
                        
                        if sql:
                            # 检测危险SQL操作
                            if check_dangerous_sql:
                                is_dangerous, dangerous_keyword = check_dangerous_sql_operations(sql)
                                if is_dangerous:
                                    response = f"[安全检测] 检测到危险操作\n\n检测到SQL中包含危险操作: {dangerous_keyword}\n为了数据安全，系统拒绝执行此查询。\n\n生成的SQL:\n```sql\n{sql}\n```"
                                    st.markdown(response)
                                    st.session_state.messages.append({"role": "assistant", "content": response})
                                    st.stop()
                            
                            # 构建响应
                            response_parts = []
                            response_parts.append(f"[意图识别] {intent_map.get(intent, '查询意图')}")
                            response_parts.append(f"正在为您查询: {prompt}")
                            response_parts.append(f"数据库: {database_type}")
                            
                            # 根据设置显示LLM信息
                            if use_llm:
                                if provider == "openai":
                                    response_parts.append(f"LLM: OpenAI - {llm_config.get('openai', {}).get('model', 'gpt-4')}")
                                elif provider == "azure_openai":
                                    response_parts.append(f"LLM: Azure OpenAI - {llm_config.get('azure_openai', {}).get('deployment_name', '')}")
                                else:  # custom
                                    response_parts.append(f"LLM: 自定义 - {llm_config.get('custom', {}).get('model', 'llama2')}")
                            
                            # 根据设置显示Schema提示
                            if show_schema:
                                response_parts.append(f"数据库Schema提示:\n```\n{schema_prompt}\n```")
                            
                            # 添加SQL - 使用更安全的格式化方式
                            response_parts.append(f"SQL: ")  # 先添加标签
                            response_parts.append(f"```sql")  # 单独一行开始代码块
                            response_parts.append(sql)       # 添加SQL代码
                            response_parts.append(f"```")    # 单独一行结束代码块
                            
                            # 组合响应
                            response = "\n\n".join(response_parts)
                            try:
                                st.markdown(response)
                            except Exception as e:
                                # 如果markdown渲染失败，尝试使用纯文本显示
                                st.text(f"Markdown渲染失败，以下是原始响应:\n{response}")
                                st.error(f"渲染错误: {str(e)}")
                            
                            # 执行查询
                            with st.spinner("执行查询中..."):
                                query_result = mcp_client.call_mcp_server_with_config(
                                    database_type,
                                    "execute_query",
                                    db_config,
                                    {"sql": sql, "database": db_config.get("database")}
                                )
                                
                                if "error" in query_result:
                                    st.error(f"查询失败: {query_result['error']}")
                                    st.session_state.messages.append({"role": "assistant", "content": response + "\n\n查询失败: " + query_result['error']})
                                elif "result" in query_result and "data" in query_result["result"]:
                                    # 将查询结果转换为DataFrame
                                    columns = query_result["result"]["data"].get("columns", [])
                                    rows = query_result["result"]["data"].get("rows", [])
                                    
                                    if rows:
                                        df = pd.DataFrame(rows, columns=columns)
                                        st.dataframe(df)
                                        st.session_state.messages.append({
                                            "role": "assistant", 
                                            "content": response,
                                            "data": df
                                        })
                                    else:
                                        st.info("查询结果为空")
                                        st.session_state.messages.append({"role": "assistant", "content": response + "\n\n查询结果为空"})
                                else:
                                    st.warning("查询结果格式不正确")
                                    st.session_state.messages.append({"role": "assistant", "content": response + "\n\n查询结果格式不正确"})
                        else:
                            tables = list(schema_info.keys())
                            response = f"我无法理解您的查询意图。请尝试以下格式:\n- 查询[表名]\n- 显示[表名]的数据\n\n可用的表: {', '.join(tables)}"
                            st.markdown(response)
                            st.session_state.messages.append({"role": "assistant", "content": response})

# 清除聊天历史
if st.button("清除历史"):
    st.session_state.messages = []
    st.rerun()