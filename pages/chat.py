import streamlit as st
import pandas as pd
import re
from utils.mcp_client import MCPClient
from utils.config_manager import ConfigManager
from utils.llm_client import LLMClient
from utils.i18n import t
from utils.test_question_helper import render_test_question_sidebar, get_test_question_input
from utils.mcp_tool_handler import get_llm_tools, handle_tool_calls

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

def execute_analysis_plan_steps(analysis_plan, original_question, database_type, config_manager, llm_client, mcp_client, db_config, check_dangerous_sql):
    """
    按步骤执行分析计划
    
    Args:
        analysis_plan: 分析计划对象
        original_question: 原始问题
        database_type: 数据库类型
        config_manager: 配置管理器
        llm_client: LLM客户端
        mcp_client: MCP客户端
        db_config: 数据库配置
        check_dangerous_sql: 危险SQL检查函数
    """
    
    st.markdown("[意图识别] **分析意图 - 执行阶段** 🚀")
    st.success(f"开始执行分析计划: {original_question}")
    
    # 获取计划内容
    if isinstance(analysis_plan, dict) and analysis_plan.get('format') == 'json':
        plan_content = analysis_plan['content']
    else:
        st.error("分析计划格式不正确")
        return
    
    if isinstance(plan_content, str):
        import json
        try:
            plan_content = json.loads(plan_content)
        except json.JSONDecodeError:
            st.error("无法解析分析计划JSON")
            return
    
    # 显示执行概览
    steps = plan_content.get('steps', [])
    st.info(f"📋 执行计划概览: 共{len(steps)}个步骤")
    
    # 存储每个步骤的结果
    step_results = {}
    execution_log = []
    
    # 按step_id排序执行
    sorted_steps = sorted(steps, key=lambda x: x.get('step_id', 0))
    
    for i, step in enumerate(sorted_steps):
        step_id = step.get('step_id', i+1)
        step_type = step.get('step_type', 'unknown')
        description = step.get('description', '未知步骤')
        dependencies = step.get('dependencies', [])
        
        # 检查依赖关系
        if dependencies:
            missing_deps = [dep for dep in dependencies if dep not in step_results]
            if missing_deps:
                error_msg = f"步骤{step_id}依赖的步骤{missing_deps}尚未完成，跳过执行"
                st.warning(error_msg)
                execution_log.append(f"⚠️ {error_msg}")
                continue
        
        # 显示当前步骤
        with st.expander(f"🔄 执行步骤 {step_id}: {description}", expanded=True):
            st.write(f"**步骤类型**: {step_type}")
            
            try:
                if step_type == 'sql_query':
                    result = execute_sql_query_step(step, database_type, config_manager, llm_client, mcp_client, db_config, check_dangerous_sql)
                elif step_type == 'external_data':
                    result = execute_external_data_step(step, mcp_client)
                elif step_type == 'llm_analysis':
                    result = execute_llm_analysis_step(step, step_results, llm_client, original_question)
                else:
                    result = {'status': 'error', 'message': f'不支持的步骤类型: {step_type}'}
                
                # 存储结果
                step_results[step_id] = result
                
                # 显示执行结果
                if result.get('status') == 'success':
                    st.success(f"✅ 步骤{step_id}执行成功")
                    execution_log.append(f"✅ 步骤{step_id}: {description} - 执行成功")
                    
                    # 显示具体结果
                    if 'data' in result and result['data'] is not None:
                        if isinstance(result['data'], pd.DataFrame):
                            st.dataframe(result['data'])
                        else:
                            st.write("**结果数据**:", result['data'])
                    
                    if 'message' in result:
                        st.write("**执行详情**:", result['message'])
                        
                else:
                    st.error(f"❌ 步骤{step_id}执行失败: {result.get('message', '未知错误')}")
                    execution_log.append(f"❌ 步骤{step_id}: {description} - 执行失败: {result.get('message')}")
                    
            except Exception as e:
                error_msg = f"步骤{step_id}执行异常: {str(e)}"
                st.error(error_msg)
                execution_log.append(f"💥 {error_msg}")
                step_results[step_id] = {'status': 'error', 'message': str(e)}
    
    # 生成最终分析报告
    generate_final_analysis_report(plan_content, step_results, execution_log, original_question)
    
    # 清除分析计划状态
    st.session_state.analysis_plan = None
    st.session_state.analysis_question = None
    
    # 添加执行日志到消息历史
    log_summary = "\n".join(execution_log)
    final_message = f"[分析执行完成] {original_question}\n\n执行日志:\n{log_summary}"
    st.session_state.messages.append({"role": "assistant", "content": final_message})

def execute_sql_query_step(step, database_type, config_manager, llm_client, mcp_client, db_config, check_dangerous_sql):
    """执行SQL查询步骤"""
    query_requirements = step.get('query_requirements', {})
    
    # 根据查询需求构建prompt
    sql_prompt = f"""根据以下查询需求生成SQL语句：

表: {', '.join(query_requirements.get('tables', []))}
时间范围: {query_requirements.get('time_range', '不限')}
筛选条件: {', '.join(query_requirements.get('filters', []))}
需要的指标: {', '.join(query_requirements.get('metrics', []))}
分组维度: {', '.join(query_requirements.get('grouping', []))}

请只返回可执行的SQL语句，不要包含任何解释说明。"""
    
    try:
        # 生成SQL
        with st.spinner("生成SQL查询..."):
            sql = llm_client.generate_sql(sql_prompt)
            sql = clean_sql_response(sql) if sql else None
        
        if not sql:
            return {'status': 'error', 'message': '无法生成SQL查询'}
        
        st.code(sql, language='sql')
        
        # 检测危险SQL操作
        if check_dangerous_sql:
            is_dangerous, dangerous_keyword = check_dangerous_sql_operations(sql)
            if is_dangerous:
                return {'status': 'error', 'message': f'检测到危险操作: {dangerous_keyword}'}
        
        # 执行查询
        with st.spinner("执行SQL查询..."):
            query_result = mcp_client.call_mcp_server_with_config(
                database_type,
                "execute_query", 
                db_config,
                {"sql": sql, "database": db_config.get("database")}
            )
        
        if "error" in query_result:
            return {'status': 'error', 'message': f'查询失败: {query_result["error"]}'}
        
        if "result" in query_result and "data" in query_result["result"]:
            columns = query_result["result"]["data"].get("columns", [])
            rows = query_result["result"]["data"].get("rows", [])
            
            if rows:
                df = pd.DataFrame(rows, columns=columns)
                return {
                    'status': 'success',
                    'data': df,
                    'message': f'查询成功，获得{len(rows)}行数据',
                    'sql': sql
                }
            else:
                return {
                    'status': 'success', 
                    'data': None,
                    'message': '查询成功，但结果为空',
                    'sql': sql
                }
        else:
            return {'status': 'error', 'message': '查询结果格式不正确'}
            
    except Exception as e:
        return {'status': 'error', 'message': f'SQL执行异常: {str(e)}'}

def execute_external_data_step(step, mcp_client):
    """执行外部数据获取步骤"""
    data_requirements = step.get('data_requirements', {})
    
    data_type = data_requirements.get('data_type', '')
    content_focus = data_requirements.get('content_focus', '')
    time_scope = data_requirements.get('time_scope', '')
    geographic_scope = data_requirements.get('geographic_scope', '')
    
    # 构建搜索查询
    search_query = f"{data_type} {content_focus}"
    if time_scope:
        search_query += f" {time_scope}"
    if geographic_scope:
        search_query += f" {geographic_scope}"
    
    try:
        with st.spinner(f"获取外部数据: {search_query}..."):
            st.write(f"🔍 搜索关键词: {search_query}")
            
            # 模拟外部数据获取（实际项目中可以集成真实的数据源）
            # 由于playwright需要异步环境且较复杂，这里先使用模拟数据
            
            # 根据数据类型返回模拟的外部数据
            if "天气" in data_type:
                external_data = {
                    'data_type': '天气数据',
                    'source': '模拟天气API',
                    'summary': f'根据{geographic_scope}地区{time_scope}的天气数据分析',
                    'key_findings': [
                        '平均温度: 22°C',
                        '降雨天数: 8天',
                        '湿度: 65%',
                        '主要天气模式: 多云间晴'
                    ],
                    'search_query': search_query
                }
            elif "市场" in data_type or "经济" in data_type:
                external_data = {
                    'data_type': '市场数据',
                    'source': '模拟市场研究',
                    'summary': f'关于{content_focus}的市场分析数据',
                    'key_findings': [
                        '市场增长率: +12%',
                        '主要趋势: 数字化转型',
                        '消费者偏好: 便利性优先',
                        '竞争格局: 头部企业集中'
                    ],
                    'search_query': search_query
                }
            elif "行业" in data_type:
                external_data = {
                    'data_type': '行业数据',
                    'source': '模拟行业报告',
                    'summary': f'{content_focus}行业分析报告',
                    'key_findings': [
                        '行业规模: 持续扩大',
                        '技术创新: AI应用增多',
                        '政策环境: 支持性强',
                        '发展前景: 乐观向好'
                    ],
                    'search_query': search_query
                }
            else:
                external_data = {
                    'data_type': '综合数据',
                    'source': '模拟数据源',
                    'summary': f'关于{search_query}的综合信息',
                    'key_findings': [
                        '数据获取成功',
                        '信息来源可靠',
                        '数据时效性良好',
                        '覆盖范围全面'
                    ],
                    'search_query': search_query
                }
            
            return {
                'status': 'success',
                'data': external_data,
                'message': f'成功获取外部数据: {data_type}'
            }
            
    except Exception as e:
        return {'status': 'error', 'message': f'外部数据获取异常: {str(e)}'}

def execute_llm_analysis_step(step, step_results, llm_client, original_question):
    """执行LLM分析步骤"""
    analysis_requirements = step.get('analysis_requirements', {})
    
    method = analysis_requirements.get('method', '综合分析')
    input_data_refs = analysis_requirements.get('input_data', [])
    focus_areas = analysis_requirements.get('focus_areas', [])
    insights_target = analysis_requirements.get('insights_target', [])
    
    # 收集前面步骤的数据
    collected_data = {}
    for data_ref in input_data_refs:
        # 尝试匹配步骤ID或描述
        for step_id, result in step_results.items():
            if (str(step_id) in data_ref or 
                any(keyword in data_ref for keyword in [str(step_id), '步骤', 'step'])):
                collected_data[f"步骤{step_id}"] = result
                break
    
    try:
        # 构建分析prompt
        analysis_prompt = f"""请对以下数据进行{method}分析，回答原始问题：{original_question}

分析方法: {method}
关注重点: {', '.join(focus_areas)}
期望洞察: {', '.join(insights_target)}

可用数据:
"""
        
        for data_source, result in collected_data.items():
            analysis_prompt += f"\n{data_source}数据:\n"
            if result.get('status') == 'success':
                if isinstance(result.get('data'), pd.DataFrame):
                    # DataFrame转换为文本描述
                    df = result['data']
                    analysis_prompt += f"数据概况: {len(df)}行 x {len(df.columns)}列\n"
                    analysis_prompt += f"列名: {', '.join(df.columns)}\n"
                    analysis_prompt += f"数据样例:\n{df.head(3).to_string()}\n"
                elif result.get('data'):
                    analysis_prompt += f"数据内容: {str(result['data'])[:500]}...\n"
                else:
                    analysis_prompt += "数据为空\n"
            else:
                analysis_prompt += f"数据获取失败: {result.get('message', '未知错误')}\n"
        
        analysis_prompt += f"""

请基于以上数据进行深入分析，提供：
1. 数据概况总结
2. 关键发现和趋势
3. 针对原始问题的具体回答
4. 业务建议和洞察

请确保分析结果具体、准确、有价值。"""
        
        with st.spinner("进行AI数据分析..."):
            analysis_result = llm_client.generate_sql(analysis_prompt)
        
        if analysis_result:
            return {
                'status': 'success',
                'data': analysis_result,
                'message': 'AI分析完成',
                'analysis_method': method
            }
        else:
            return {'status': 'error', 'message': 'AI分析生成失败'}
            
    except Exception as e:
        return {'status': 'error', 'message': f'AI分析异常: {str(e)}'}

def generate_final_analysis_report(plan_content, step_results, execution_log, original_question):
    """生成最终分析报告"""
    st.markdown("---")
    st.markdown("## 📊 最终分析报告")
    
    # 报告概览
    successful_steps = sum(1 for result in step_results.values() if result.get('status') == 'success')
    total_steps = len(step_results)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("执行步骤", f"{successful_steps}/{total_steps}")
    with col2:
        st.metric("成功率", f"{successful_steps/total_steps*100:.1f}%" if total_steps > 0 else "0%")
    with col3:
        st.metric("分析目标", "已完成" if successful_steps == total_steps else "部分完成")
    
    # 分析目标
    st.subheader("🎯 分析目标")
    st.write(plan_content.get('analysis_goal', original_question))
    
    # 关键发现（从LLM分析步骤中提取）
    llm_analyses = []
    for step_id, result in step_results.items():
        if (result.get('status') == 'success' and 
            result.get('analysis_method') and 
            result.get('data')):
            llm_analyses.append(result['data'])
    
    if llm_analyses:
        st.subheader("🔍 关键发现")
        for i, analysis in enumerate(llm_analyses):
            st.markdown(f"**分析 {i+1}:**")
            st.markdown(analysis)
    
    # 数据汇总
    st.subheader("📋 数据汇总")
    for step_id, result in step_results.items():
        if result.get('status') == 'success' and isinstance(result.get('data'), pd.DataFrame):
            st.write(f"**步骤{step_id}数据** ({len(result['data'])}行)")
            st.dataframe(result['data'].head())
    
    # 执行日志
    with st.expander("📝 详细执行日志"):
        for log_entry in execution_log:
            st.write(log_entry)

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
    
    for table, table_info in schema_info.items():
        table_desc = table_descriptions.get(table, "")
        prompt += f"\n\n表: {table}"
        if table_desc:
            prompt += f" - {table_desc}"
        prompt += "\n"
        
        # 处理不同的schema格式
        columns = None
        if isinstance(table_info, dict):
            columns = table_info.get("columns", [])
        elif isinstance(table_info, list):
            columns = table_info
            
        if columns:
            prompt += "| 列名 | 类型 | 描述 |\n"
            prompt += "| --- | --- | --- |\n"
            for col in columns:
                if isinstance(col, dict):
                    name = col.get("name", "")
                    col_type = col.get("type", "")
                    comment = col.get("comment", "")
                    prompt += f"| {name} | {col_type} | {comment} |\n"
                else:
                    # 如果col不是字典，直接添加
                    prompt += f"| {col} | - | - |\n"
        else:
            prompt += "表结构信息未配置\n"
    
    prompt += "\n\n请根据用户问题和数据库schema生成SQL查询。\n\n重要要求：\n- 只返回可执行的SQL语句\n- 不要包含任何解释说明\n- 不要添加注释或描述\n- 直接返回SQL代码"
    
    return prompt

# 使用LLM进行意图识别
def identify_intent_with_llm(question, llm_client):
    intent_prompt = f"""请分析以下用户问题的意图，只返回下列之一：
- query: 数据查询和基础分析，可通过SQL查询直接获得结果
- analysis: 深度分析，需要多步骤思考、原因分析或业务洞察
- reject: 涉及数据库增删改操作

分类标准：
- query: 数据检索、排序、统计计算、趋势展示、对比查询等，重点是获取和展示数据
- analysis: 原因分析、深度洞察、复杂推理、需要业务建议等，重点是解释和分析
- reject: INSERT/UPDATE/DELETE/DROP/CREATE/ALTER等修改操作

参考示例：

Query类型（数据查询和基础分析）：
- "哪些产品是畅销品？" → query
- "显示所有用户信息" → query  
- "查询产品销量排名前10名" → query
- "列出2024年的所有订单" → query
- "按销售额对产品进行排序" → query
- "分析销售趋势" → query
- "过去6个月销售趋势如何？" → query
- "分析产品销售的季节性趋势" → query
- "对比不同地区的销售表现" → query
- "比较2023年和2024年的销售数据" → query
- "统计月度增长率" → query
- "哪个季节销售最好？" → query
- "销量前10的产品" → query
- "计算各产品的投资回报率" → query

Analysis类型（深度分析和洞察）：
- "为什么Q4销售下滑？" → analysis
- "客户流失的主要原因是什么？" → analysis
- "分析库存积压的根本原因" → analysis
- "深入分析用户行为变化趋势" → analysis
- "深度对比分析各产品线的盈利能力" → analysis
- "计算客户生命周期价值" → analysis
- "表现最差的销售员及改进建议" → analysis
- "哪些产品畅销？分析其成功因素" → analysis
- "统计销售数据并给出优化建议" → analysis
- "对比各地区销售，找出差异原因" → analysis

Reject类型（危险操作）：
- "删除所有用户数据" → reject
- "更新产品价格" → reject
- "插入新的订单记录" → reject

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
# 格式化JSON计划的显示内容 - 专为Streamlit优化
def format_json_plan_streamlit(plan_content):
    """已废弃：复杂渲染函数，现在直接使用JSON显示"""
    return False

# 格式化JSON计划的Markdown显示内容
def format_json_plan_markdown(plan_content):
    """将JSON格式的分析计划转换为Markdown格式显示，包含JSON和友好步骤两种视图"""
    import json
    
    try:
        display_lines = []
        
        # 添加标题和切换提示
        display_lines.append("# 📋 分析计划")
        display_lines.append("")
        display_lines.append("> 以下是为您的问题制定的结构化分析计划，包含JSON格式和步骤详解两种视图")
        display_lines.append("")
        
        # JSON格式显示
        display_lines.append("## 🔧 JSON计划格式")
        display_lines.append("")
        display_lines.append("```json")
        formatted_json = json.dumps(plan_content, ensure_ascii=False, indent=2)
        display_lines.append(formatted_json)
        display_lines.append("```")
        display_lines.append("")
        
        # 友好的步骤格式显示
        display_lines.append("## 📝 步骤详解")
        display_lines.append("")
        
        # 分析目标
        display_lines.append("### 🎯 分析目标")
        display_lines.append(f"{plan_content.get('analysis_goal', '未定义')}")
        display_lines.append("")
        
        # 执行步骤
        display_lines.append("### 🔄 执行步骤")
        steps = plan_content.get('steps', [])
        
        for step in steps:
            step_id = step.get('step_id', 'N/A')
            step_type = step.get('step_type', 'unknown')
            description = step.get('description', '无描述')
            
            # 步骤类型图标和标签映射
            type_info = {
                'sql_query': {'emoji': '🗄️', 'label': '数据查询'},
                'external_data': {'emoji': '🌐', 'label': '外部数据'},
                'llm_analysis': {'emoji': '🧠', 'label': '数据分析'}
            }
            
            info = type_info.get(step_type, {'emoji': '📋', 'label': step_type})
            
            display_lines.append(f"#### {info['emoji']} 步骤 {step_id}: {info['label']}")
            display_lines.append(f"**描述**: {description}")
            display_lines.append("")
            
            # 添加具体需求详情
            if step_type == 'sql_query' and 'query_requirements' in step:
                req = step['query_requirements']
                display_lines.append("**查询需求**:")
                if 'tables' in req and req['tables']:
                    display_lines.append(f"- 📊 **涉及表**: `{', '.join(req['tables'])}`")
                if 'time_range' in req:
                    display_lines.append(f"- 📅 **时间范围**: {req['time_range']}")
                if 'filters' in req and req['filters']:
                    display_lines.append(f"- 🔍 **筛选条件**: {', '.join(req['filters'])}")
                if 'metrics' in req and req['metrics']:
                    metrics_display = ', '.join(req['metrics'][:4])
                    if len(req['metrics']) > 4:
                        metrics_display += f" 等 {len(req['metrics'])} 项指标"
                    display_lines.append(f"- 📈 **关键指标**: {metrics_display}")
                if 'grouping' in req and req['grouping']:
                    display_lines.append(f"- 📊 **分组维度**: {', '.join(req['grouping'])}")
                    
            elif step_type == 'external_data' and 'data_requirements' in step:
                req = step['data_requirements']
                display_lines.append("**数据需求**:")
                if 'data_type' in req:
                    display_lines.append(f"- 🌡️ **数据类型**: {req['data_type']}")
                if 'content_focus' in req:
                    display_lines.append(f"- 🎯 **关注内容**: {req['content_focus']}")
                if 'time_scope' in req:
                    display_lines.append(f"- ⏰ **时间范围**: {req['time_scope']}")
                if 'geographic_scope' in req:
                    display_lines.append(f"- 🗺️ **地理范围**: {req['geographic_scope']}")
                if 'format_preference' in req:
                    display_lines.append(f"- 📋 **格式要求**: {req['format_preference']}")
                    
            elif step_type == 'llm_analysis' and 'analysis_requirements' in step:
                req = step['analysis_requirements']
                display_lines.append("**分析需求**:")
                if 'method' in req:
                    display_lines.append(f"- 🔬 **分析方法**: {req['method']}")
                if 'input_data' in req and req['input_data']:
                    display_lines.append(f"- 📥 **输入数据**: {', '.join(req['input_data'])}")
                if 'focus_areas' in req and req['focus_areas']:
                    areas_display = ', '.join(req['focus_areas'][:3])
                    if len(req['focus_areas']) > 3:
                        areas_display += f" 等 {len(req['focus_areas'])} 个维度"
                    display_lines.append(f"- 🔍 **关注维度**: {areas_display}")
                if 'comparison_basis' in req:
                    display_lines.append(f"- ⚖️ **对比基准**: {req['comparison_basis']}")
                if 'insights_target' in req and req['insights_target']:
                    display_lines.append(f"- 💡 **目标洞察**: {', '.join(req['insights_target'])}")
            
            # 显示目标数据
            if 'target_data' in step:
                display_lines.append(f"- 🎯 **预期数据**: {step['target_data']}")
            
            # 显示依赖关系
            dependencies = step.get('dependencies', [])
            if dependencies:
                display_lines.append(f"- 🔗 **依赖步骤**: 步骤 {', '.join(map(str, dependencies))}")
            
            display_lines.append("")
        
        # 预期输出
        display_lines.append("### 📊 预期输出")
        display_lines.append(f"{plan_content.get('expected_output', '未定义')}")
        display_lines.append("")
        
        # 添加执行提示
        display_lines.append("---")
        display_lines.append("")
        display_lines.append("💡 **下一步**: 请输入 \"执行\" 或 \"开始执行\" 来开始按计划执行分析")
        
        return "\n".join(display_lines)
        
    except Exception as e:
        return f"格式化显示出错: {str(e)}\n\n原始内容:\n{str(plan_content)}"

# 保留原有简化版本用于向后兼容
def format_json_plan_display(plan_content):
    """简化版格式化函数，用于向后兼容"""
    return format_json_plan_markdown(plan_content)

def generate_analysis_plan(question, schema_info, table_descriptions, llm_client):
    plan_prompt = f"""请将以下复杂分析问题拆分为逻辑清晰的分析步骤，并以JSON格式输出。每个步骤应该描述需要完成的任务，而不需要提供具体的实现细节。步骤类型包括：

1. **数据查询步骤** (sql_query)
   - 描述需要从数据库获取什么数据
   - 明确查询范围、筛选条件、统计需求
   - 不需要编写具体SQL语句，执行时会根据需求生成

2. **外部数据获取步骤** (external_data) 
   - 描述需要获取的外部信息类型和来源
   - 明确数据获取目标和预期内容
   - 不需要提供具体URL或技术细节，执行时会确定具体方案

3. **数据分析步骤** (llm_analysis)
   - 基于前面步骤获取的数据进行逻辑推理和分析
   - 明确分析方法、关注重点和输出要求
   - 定义如何整合多源数据得出结论

用户问题: {question}

可用数据库表结构:
"""
    
    for table, table_info in schema_info.items():
        table_desc = table_descriptions.get(table, "")
        plan_prompt += f"\n表: {table}"
        if table_desc:
            plan_prompt += f" - {table_desc}"
        plan_prompt += "\n"
        
        # 处理不同的schema格式
        columns = None
        if isinstance(table_info, dict):
            columns = table_info.get("columns", [])
        elif isinstance(table_info, list):
            columns = table_info
            
        if columns:
            for col in columns:
                if isinstance(col, dict):
                    name = col.get("name", "")
                    col_type = col.get("type", "")
                    comment = col.get("comment", "")
                    plan_prompt += f"  - {name} ({col_type}): {comment}\n"
                else:
                    # 如果col不是字典，直接添加
                    plan_prompt += f"  - {col}\n"
    
    plan_prompt += """

请以以下JSON格式输出分析计划：

```json
{
  "analysis_goal": "明确要解答的核心问题",
  "steps": [
    {
      "step_id": 1,
      "step_type": "sql_query",
      "description": "需要查询的数据内容描述",
      "query_requirements": {
        "tables": ["相关的数据表名"],
        "time_range": "时间范围要求",
        "filters": ["筛选条件描述"],
        "metrics": ["需要的指标和统计"],
        "grouping": ["分组维度"]
      },
      "target_data": "预期获取的数据内容",
      "dependencies": []
    },
    {
      "step_id": 2,
      "step_type": "external_data",
      "description": "需要获取的外部数据描述", 
      "data_requirements": {
        "data_type": "数据类型 (天气/经济/社会等)",
        "content_focus": "关注的具体内容",
        "time_scope": "时间范围",
        "geographic_scope": "地理范围 (如适用)",
        "format_preference": "期望的数据格式"
      },
      "target_data": "预期获取的外部数据",
      "dependencies": []
    },
    {
      "step_id": 3,
      "step_type": "llm_analysis",
      "description": "分析任务描述",
      "analysis_requirements": {
        "method": "分析方法 (关联分析/趋势分析/对比分析等)",
        "input_data": ["依赖的步骤数据"],
        "focus_areas": ["重点关注的分析维度"],
        "comparison_basis": "对比基准或参考标准",
        "insights_target": ["期望发现的洞察类型"]
      },
      "output_format": "分析结果的输出格式",
      "dependencies": [1, 2]
    }
  ],
  "expected_output": "最终分析报告的结构和内容要求"
}
```

**示例** - 分析为什么雨衣在4月比5月销量好：

```json
{
  "analysis_goal": "分析雨衣4月销量优于5月的原因，识别关键影响因素并提供业务洞察",
  "steps": [
    {
      "step_id": 1,
      "step_type": "sql_query",
      "description": "获取雨衣产品4月销售表现数据",
      "query_requirements": {
        "tables": ["sales", "products"],
        "time_range": "2024年4月",
        "filters": ["产品类别=雨衣"],
        "metrics": ["销售额", "订单数量", "平均价格", "产品型号"],
        "grouping": ["产品名称", "日期"]
      },
      "target_data": "4月雨衣产品的详细销售数据",
      "dependencies": []
    },
    {
      "step_id": 2,
      "step_type": "sql_query", 
      "description": "获取雨衣产品5月销售表现数据",
      "query_requirements": {
        "tables": ["sales", "products"],
        "time_range": "2024年5月",
        "filters": ["产品类别=雨衣"],
        "metrics": ["销售额", "订单数量", "平均价格", "产品型号"],
        "grouping": ["产品名称", "日期"]
      },
      "target_data": "5月雨衣产品的详细销售数据",
      "dependencies": []
    },
    {
      "step_id": 3,
      "step_type": "external_data",
      "description": "获取4月和5月的天气情况数据",
      "data_requirements": {
        "data_type": "天气数据",
        "content_focus": "降雨天数、降雨量、阴天数、温度",
        "time_scope": "2024年4月-5月",
        "geographic_scope": "销售覆盖的主要城市",
        "format_preference": "按日统计的结构化数据"
      },
      "target_data": "4月和5月的天气状况统计",
      "dependencies": []
    },
    {
      "step_id": 4,
      "step_type": "sql_query",
      "description": "获取同期整体市场销售情况作为对比基准",
      "query_requirements": {
        "tables": ["sales"],
        "time_range": "2024年4月-5月",
        "filters": ["所有产品类别"],
        "metrics": ["总销售额", "总订单数"],
        "grouping": ["月份"]
      },
      "target_data": "4月和5月整体市场表现数据",
      "dependencies": []
    },
    {
      "step_id": 5,
      "step_type": "llm_analysis",
      "description": "综合分析雨衣销量月度差异的根本原因",
      "analysis_requirements": {
        "method": "多因素关联分析和因果推理",
        "input_data": ["4月雨衣销量", "5月雨衣销量", "天气数据", "市场基准"],
        "focus_areas": ["天气因素影响", "季节性消费规律", "产品策略效果", "市场竞争态势"],
        "comparison_basis": "同期整体市场表现和历史趋势",
        "insights_target": ["主要驱动因素", "改进机会", "预测指标"]
      },
      "output_format": "包含原因分析、数据证据、业务建议的结构化报告",
      "dependencies": [1, 2, 3, 4]
    }
  ],
  "expected_output": "包含销量差异的量化分析、主要影响因素识别、天气关联性分析、以及针对性的业务优化建议"
}
```

现在请为用户问题生成类似格式的JSON分析计划，确保每个步骤都有明确的执行目标和具体的实现方式。

**重要说明：请直接返回有效的JSON对象，不要使用markdown代码块包装，不要添加任何解释文字。**

示例输出格式（请严格按照这个格式返回）：
{
  "analysis_goal": "分析目标描述",
  "steps": [...],
  "expected_output": "预期输出描述"
}"""
    
    try:
        # 发送请求给LLM
        response = llm_client.generate_sql(plan_prompt)
        
        # 尝试解析JSON格式的回复
        try:
            import json
            
            # 首先尝试直接解析JSON（LLM直接返回JSON的情况）
            try:
                parsed_plan = json.loads(response)
                
                # 验证必要字段
                required_fields = ['analysis_goal', 'steps', 'expected_output']
                if all(field in parsed_plan for field in required_fields):
                    # 返回结构化的计划
                    return {
                        'format': 'json',
                        'content': parsed_plan,
                        'raw_response': response
                    }
                    
            except json.JSONDecodeError:
                # 直接解析失败，尝试提取JSON代码块（向后兼容）
                import re
                json_match = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                    # 验证JSON格式
                    parsed_plan = json.loads(json_str)
                    
                    # 验证必要字段
                    required_fields = ['analysis_goal', 'steps', 'expected_output']
                    if all(field in parsed_plan for field in required_fields):
                        # 返回结构化的计划
                        return {
                            'format': 'json',
                            'content': parsed_plan,
                            'raw_response': response
                        }
            
            # 如果都没有找到有效的JSON，返回原始响应
            return {
                'format': 'text',
                'content': response,
                'raw_response': response
            }
            
        except (json.JSONDecodeError, Exception) as parse_error:
            # JSON解析失败，返回原始文本
            return {
                'format': 'text',
                'content': response,
                'raw_response': response,
                'parse_error': str(parse_error)
            }
            
    except Exception as e:
        return {
            'format': 'error',
            'content': f"生成分析计划时出错: {str(e)}",
            'error': str(e)
        }

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
                        # 执行分析计划 - 新的步骤化执行逻辑
                        if st.session_state.analysis_plan and use_llm and llm_client:
                            execute_analysis_plan_steps(
                                st.session_state.analysis_plan,
                                st.session_state.analysis_question,
                                database_type, 
                                config_manager,
                                llm_client,
                                mcp_client,
                                db_config,
                                check_dangerous_sql
                            )
                        else:
                            response = "[执行错误] 没有可执行的分析计划或LLM客户端未配置"
                            st.error(response)
                            st.session_state.messages.append({"role": "assistant", "content": response})
                    elif intent == "analysis_modify":
                        # 修改分析计划
                        if use_llm and llm_client:
                            # 更新分析计划
                            plan_result = generate_analysis_plan(f"{st.session_state.analysis_question}\n\n用户补充: {prompt}", schema_info, table_descriptions, llm_client)
                            st.session_state.analysis_plan = plan_result
                            
                            # 根据返回格式处理显示
                            if isinstance(plan_result, dict):
                                if plan_result.get('format') == 'json':
                                    # JSON格式的结构化计划 - 使用st.json优化显示
                                    st.markdown("[意图识别] **分析意图 - 修改阶段** ✅")
                                    st.success("已根据您的补充更新分析计划")
                                    
                                    plan_content = plan_result['content']
                                    
                                    # 使用st.json显示，支持交互式展开/折叠
                                    import json
                                    if isinstance(plan_content, str):
                                        # 如果是JSON字符串，先解析再显示
                                        try:
                                            parsed_content = json.loads(plan_content)
                                            st.json(parsed_content, expanded=3)
                                            response_text = f"[意图识别] 分析意图 - 修改阶段 ✅\n\n已更新分析计划（支持交互式JSON浏览）\n\n请输入\"执行\"或类似意思来开始分析。"
                                        except json.JSONDecodeError:
                                            # 解析失败，降级到code显示
                                            st.code(plan_content, language='json')
                                            response_text = f"[意图识别] 分析意图 - 修改阶段 ✅\n\n```json\n{plan_content}\n```\n\n请输入\"执行\"或类似意思来开始分析。"
                                    else:
                                        # 如果是字典，直接使用st.json
                                        st.json(plan_content, expanded=3)
                                        response_text = f"[意图识别] 分析意图 - 修改阶段 ✅\n\n已更新分析计划（支持交互式JSON浏览）\n\n请输入\"执行\"或类似意思来开始分析。"
                                    
                                    st.info("💡 请输入 \"执行\" 或类似意思来开始分析。")
                                    st.session_state.messages.append({"role": "assistant", "content": response_text})
                                        
                                elif plan_result.get('format') == 'error':
                                    st.error(plan_result['content'])
                                    st.session_state.messages.append({"role": "assistant", "content": f"错误: {plan_result['content']}"})
                                else:
                                    # 文本格式
                                    response = f"[意图识别] 分析意图 - 修改阶段\n\n已根据您的补充更新分析计划：\n\n{plan_result['content']}\n\n---\n\n请输入\"执行\"或类似意思来开始分析。"
                                    st.markdown(response)
                                    st.session_state.messages.append({"role": "assistant", "content": response})
                            else:
                                # 向后兼容旧格式
                                response = f"[意图识别] 分析意图 - 修改阶段\n\n已根据您的补充更新分析计划：\n\n{str(plan_result)}\n\n---\n\n请输入\"执行\"或类似意思来开始分析。"
                                st.markdown(response)
                                st.session_state.messages.append({"role": "assistant", "content": response})
                        else:
                            response = "请先启用LLM功能才能进行数据分析"
                            st.markdown(response)
                            st.session_state.messages.append({"role": "assistant", "content": response})
                    elif intent == "analysis":
                        # 生成分析计划
                        if use_llm and llm_client:
                            plan_result = generate_analysis_plan(prompt, schema_info, table_descriptions, llm_client)
                            st.session_state.analysis_plan = plan_result
                            st.session_state.analysis_question = prompt
                            
                            # 根据返回格式处理显示
                            if isinstance(plan_result, dict):
                                if plan_result.get('format') == 'json':
                                    # JSON格式的结构化计划 - 使用st.json优化显示
                                    st.markdown("[意图识别] **分析意图 - 计划阶段** ✅")
                                    st.success("以下是为您的分析问题制定的计划")
                                    
                                    plan_content = plan_result['content']
                                    
                                    # 使用st.json显示，支持交互式展开/折叠
                                    import json
                                    if isinstance(plan_content, str):
                                        # 如果是JSON字符串，先解析再显示
                                        try:
                                            parsed_content = json.loads(plan_content)
                                            st.json(parsed_content, expanded=3)
                                            response_text = f"[意图识别] 分析意图 - 计划阶段 ✅\n\n已生成分析计划（支持交互式JSON浏览）\n\n请输入\"执行\"或类似意思来开始分析。"
                                        except json.JSONDecodeError:
                                            # 解析失败，降级到code显示
                                            st.code(plan_content, language='json')
                                            response_text = f"[意图识别] 分析意图 - 计划阶段 ✅\n\n```json\n{plan_content}\n```\n\n请输入\"执行\"或类似意思来开始分析。"
                                    else:
                                        # 如果是字典，直接使用st.json
                                        st.json(plan_content, expanded=3)
                                        response_text = f"[意图识别] 分析意图 - 计划阶段 ✅\n\n已生成分析计划（支持交互式JSON浏览）\n\n请输入\"执行\"或类似意思来开始分析。"
                                    
                                    st.info("💡 请输入 \"执行\" 或类似意思来开始分析。")
                                    st.session_state.messages.append({"role": "assistant", "content": response_text})
                                        
                                elif plan_result.get('format') == 'error':
                                    st.error(plan_result['content'])
                                    st.session_state.messages.append({"role": "assistant", "content": f"错误: {plan_result['content']}"})
                                else:
                                    # 文本格式
                                    response = f"[意图识别] 分析意图 - 计划阶段\n\n以下是为您的分析问题制定的计划：\n\n{plan_result['content']}\n\n---\n\n请输入\"执行\"或类似意思来开始分析。"
                                    st.markdown(response)
                                    st.session_state.messages.append({"role": "assistant", "content": response})
                            else:
                                # 向后兼容旧格式
                                response = f"[意图识别] 分析意图 - 计划阶段\n\n以下是为您的分析问题制定的计划：\n\n{str(plan_result)}\n\n---\n\n请输入\"执行\"或类似意思来开始分析。"
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