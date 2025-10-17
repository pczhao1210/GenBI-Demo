import streamlit as st
import pandas as pd
import re
from utils.mcp_client import MCPClient
from utils.config_manager import ConfigManager
from utils.llm_client import LLMClient
from utils.i18n import t
from utils.test_question_helper import render_test_question_sidebar, get_test_question_input

def clean_sql_response(sql_text):
    """清理LLM响应中的SQL，去掉多余的解释内容"""
    if not sql_text:
        return sql_text
    
    lines = sql_text.strip().split('\n')
    sql_lines = []
    
    for line in lines:
        line = line.strip()
        
        # 跳过空行
        if not line:
            continue
            
        # 跳过明显的解释性文字（中文和英文）
        if (line.startswith('下面的') or line.startswith('以下') or 
            line.startswith('This query') or line.startswith('The following') or
            line.startswith('这个') or line.startswith('该') or
            '会统计' in line or 'will calculate' in line or
            '按.*排列' in line or 'ordered by' in line.lower() or
            line.startswith('注意：') or line.startswith('Note:')):
            continue
            
        # 跳过纯中文解释行（不包含SQL关键字）
        if (re.match(r'^[^\x00-\x7F，。：；！？（）【】""''、]+[，。：；！？]*$', line) and
            not any(keyword in line.upper() for keyword in 
                   ['SELECT', 'FROM', 'WHERE', 'GROUP', 'ORDER', 'INSERT', 'UPDATE', 'DELETE'])):
            continue
            
        # 保留SQL语句行
        sql_lines.append(line)
    
    # 重新组合SQL
    cleaned_sql = '\n'.join(sql_lines).strip()
    
    # 如果清理后为空，返回原文
    if not cleaned_sql:
        return sql_text
        
    return cleaned_sql

st.set_page_config(page_title="Smart Chat", page_icon="💬", layout="wide")
st.title(t('smart_chat'))

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
    st.header(t('settings'))
    
    # 数据库选择
    database_type = st.selectbox(t('select_database'), ["mysql", "athena"])
    
    # 加载数据库配置
    db_config = config_manager.load_database_config().get(database_type, {})
    if not db_config:
        st.warning(t('config_db_connection_first').format(db_type=database_type.upper()))
    
    # 加载LLM配置
    llm_config = config_manager.load_llm_config()
    
    # LLM模型选择
    st.subheader(t('llm_model_settings'))
    provider = st.selectbox(
        t('llm_provider'),
        ["openai", "azure_openai", "custom"],
        index=["openai", "azure_openai", "custom"].index(llm_config.get("provider", "openai"))
    )
    
    # 显示当前选择的模型
    if provider == "openai":
        # 直接使用配置文件中的模型，无需验证
        current_model = llm_config.get("openai", {}).get("model", "gpt-4")
        st.info(f"{t('current_using')}: OpenAI - {current_model}")
        # 将当前模型赋值给model变量，用于后续的API调用
        model = current_model
    elif provider == "azure_openai":
        deployment = llm_config.get("azure_openai", {}).get("deployment_name", "")
        st.info(f"{t('current_using')}: Azure OpenAI - {deployment}")
    else:  # custom
        model = llm_config.get("custom", {}).get("model", "llama2")
        st.info(f"{t('current_using')}: Custom - {model}")
    
    # 其他设置
    st.subheader(t('display_settings'))
    show_schema = st.checkbox(t('show_schema_prompt'), value=True)
    use_llm = st.checkbox(t('use_llm_generate_sql'), value=True)
    
    st.subheader(t('security_settings'))
    check_dangerous_sql = st.checkbox(t('avoid_dangerous_code'), value=True)
    
    # 初始化LLM客户端
    llm_client = LLMClient(llm_config)

# 渲染测试问题助手侧边栏
render_test_question_sidebar()

# 显示聊天历史
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "data" in message:
            try:
                # 确保数据类型兼容性
                df = message["data"]
                if isinstance(df, pd.DataFrame):
                    # 转换所有列为字符串以避免类型冲突
                    df_display = df.astype(str)
                    st.dataframe(df_display)
                else:
                    st.dataframe(df)
            except Exception as e:
                st.error(f"数据显示错误: {str(e)}")
                st.write(message["data"])

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
    
    prompt += "\n\n请根据用户问题和数据库schema生成SQL查询。\n\n重要要求：\n- 只返回可执行的SQL语句\n- 不要包含任何解释说明\n- 不要添加注释或描述\n- 直接返回SQL代码"
    
    return prompt

# 使用LLM进行意图识别
def identify_intent_with_llm(question, llm_client):
    intent_prompt = f"""请分析以下用户问题的意图，只返回下列之一：
- query: 数据查询（包括简单查询、排序查询、筛选查询等）
- analysis: 复杂的数据分析（如：趋势分析、多维对比分析、统计计算、关联分析等）
- reject: 涉及数据库增删改操作（INSERT/UPDATE/DELETE/DROP/CREATE/ALTER等）

用户问题: {question}

分类指导：
- query意图：查询、显示、列出、哪些、前N名、排序、筛选等单表或者多表join的查询需求，包括趋势分析，多维对比等
- analysis意图：无法从单一query给出问题的答案，需要先进行问题思维链拆分后再逐步进行原因分析，回答'为什么'等复杂分析需求
- reject意图：任何修改数据的操作

示例：
- "哪些产品是畅销品" → query（按销量排序查询）
- "查询产品信息" → query（简单查询）
- "分析过去6个月的销售趋势变化" → query（趋势分析）
- "对比不同地区的销售表现" → query（多维对比）
- "为什么2023年的订单少于2024年" → analysis（需要分析原因）

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
    """使用LLM生成SQL查询"""
    # 获取保存的schema信息
    schema_info, table_descriptions = get_saved_schema(config_manager, database_type)
    
    if not schema_info:
        return None, ""
    
    # 构建包含schema的prompt
    schema_prompt = build_schema_prompt(question, schema_info, table_descriptions)
    
    sql = None
    
    # 只有启用LLM且有LLM客户端时才生成SQL
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
                
                # 清理SQL：去掉多余的解释内容
                if sql:
                    sql = clean_sql_response(sql)
        except Exception as e:
            print(f"LLM生成SQL时出错: {str(e)}")
            sql = None
    
    # 返回生成的SQL和包含schema的prompt
    return sql, schema_prompt
    
    # 返回生成的SQL和包含schema的prompt
    return sql, schema_prompt

# 检查是否有测试问题输入
test_question = get_test_question_input()
if test_question:
    prompt = test_question
else:
    prompt = None

# 聊天输入
if not prompt:
    prompt = st.chat_input(t('enter_question'))

if prompt:
    # 添加用户消息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 生成助手回复
    with st.chat_message("assistant"):
        with st.spinner(t('thinking')):
            if not db_config:
                response = t('config_db_connection_first').format(db_type=database_type.upper())
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
            else:
                # 检查是否有保存的schema
                schema_info, table_descriptions = get_saved_schema(config_manager, database_type)
                
                if not schema_info:
                    response = t('config_schema_first').format(db_type=database_type.upper())
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
                                            try:
                                                df = pd.DataFrame(rows, columns=columns)
                                                # 转换所有列为字符串以避免类型冲突
                                                df_display = df.astype(str)
                                                st.dataframe(df_display)
                                                st.session_state.messages.append({
                                                    "role": "assistant", 
                                                    "content": response,
                                                    "data": df_display
                                                })
                                            except Exception as e:
                                                st.error(f"数据显示错误: {str(e)}")
                                                st.write("原始数据:", rows)
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
                            
                            # 根据设置显示Schema提示（使用可折叠的expander）
                            if show_schema:
                                with st.expander("📋 数据库Schema提示", expanded=False):
                                    st.markdown(f"```\n{schema_prompt}\n```")
                            
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
                                        try:
                                            df = pd.DataFrame(rows, columns=columns)
                                            # 转换所有列为字符串以避免类型冲突
                                            df_display = df.astype(str)
                                            st.dataframe(df_display)
                                            st.session_state.messages.append({
                                                "role": "assistant", 
                                                "content": response,
                                                "data": df_display
                                            })
                                        except Exception as e:
                                            st.error(f"数据显示错误: {str(e)}")
                                            st.write("原始数据:", rows)
                                    else:
                                        st.info("查询结果为空")
                                        st.session_state.messages.append({"role": "assistant", "content": response + "\n\n查询结果为空"})
                                else:
                                    st.warning("查询结果格式不正确")
                                    st.session_state.messages.append({"role": "assistant", "content": response + "\n\n查询结果格式不正确"})
                        else:
                            # SQL生成失败的处理
                            tables = list(schema_info.keys())
                            
                            if use_llm:
                                # 已启用LLM但生成失败
                                response = f"""很抱歉，LLM未能为您的问题生成SQL查询。

**您的问题**: {prompt}

**可能的原因**:
1. 问题描述过于复杂或模糊
2. LLM服务暂时不可用
3. 问题超出了当前数据库结构的支持范围

**建议**:
- 尝试将问题表述得更具体和明确
- 检查LLM配置是否正确
- 参考可用的表结构调整问题

**可用的表**: {', '.join(tables)}

请重新组织您的问题，或联系管理员检查LLM配置。"""
                            else:
                                # 未启用LLM
                                response = f"""为了回答您的问题 "{prompt}"，需要启用LLM功能。

**启用步骤**:
1. 在页面顶部勾选"使用LLM进行SQL生成"
2. 确保LLM配置正确（在LLM配置页面设置）
3. 重新提问

**可用的表**: {', '.join(tables)}

**说明**: 系统现在仅支持通过LLM生成SQL查询，不再提供基于规则的简单查询功能。"""
                            
                            st.markdown(response)
                            st.session_state.messages.append({"role": "assistant", "content": response})

# 清除聊天历史
if st.button(t('clear_history')):
    st.session_state.messages = []
    st.rerun()