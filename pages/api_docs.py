import streamlit as st
import requests
from utils.i18n import t

st.set_page_config(page_title="API Documentation", page_icon="📚")
st.title(f"📚 {t('api_docs')}")

# API服务状态
st.subheader(t('service_status'))
col1, col2 = st.columns(2)

with col1:
    try:
        # TODO: 实际检查API状态
        backend_status = t('running')
    except:
        backend_status = t('offline')
    st.metric("Backend API", backend_status)

with col2:
    try:
        # 检查API服务状态
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            api_status = t('normal')
        else:
            api_status = t('abnormal')
    except:
        api_status = t('offline')
    st.metric(t('api_service'), api_status)

# API端点列表
st.subheader(t('api_endpoints'))

endpoints = [
    {"method": "POST", "path": "/query", "description": t('execute_data_query')},
    {"method": "POST", "path": "/analyze", "description": t('execute_data_analysis')},
    {"method": "POST", "path": "/optimize-chain", "description": t('optimize_analysis_chain')},
    {"method": "POST", "path": "/generate-sql", "description": t('generate_sql_statement'), "highlight": True},
    {"method": "GET", "path": "/health", "description": t('service_health_check')}
]

for endpoint in endpoints:
    method_color = {
        "GET": "🟢",
        "POST": "🔵",
        "PUT": "🟡",
        "DELETE": "🔴"
    }
    
    # 特殊标记新增的API
    highlight = endpoint.get('highlight', False)
    prefix = "🆕 " if highlight else ""
    
    st.markdown(f"""
    **{prefix}{method_color.get(endpoint['method'], '⚪')} {endpoint['method']}** `{endpoint['path']}`  
    {endpoint['description']}
    """)

st.divider()

# Swagger UI链接
st.subheader(t('detailed_docs'))
col1, col2 = st.columns(2)

with col1:
    if st.button(t('swagger_ui_docs'), type="primary"):
        st.markdown(f"[Swagger UI](http://localhost:8000/docs) - {t('open_in_new_tab')}")

with col2:
    if st.button(t('api_test_tool'), type="secondary"):
        st.markdown(f"[ReDoc Documentation](http://localhost:8000/redoc) - {t('open_in_new_tab')}")

# API测试区域
st.subheader(t('api_testing'))
with st.expander(t('quick_test_api')):
    test_endpoint = st.selectbox(t('select_endpoint'), [ep["path"] for ep in endpoints])
    
    if test_endpoint == "/generate-sql":
        st.markdown(f"**{t('test_sql_generation_api')}**")
        question = st.text_input(t('input_query'), value="显示前10行数据")
        database = st.selectbox(t('database_type'), ["athena", "mysql"])
        
        if st.button(t('generate_sql')):
            try:
                response = requests.post(
                    "http://localhost:8000/generate-sql",
                    json={"question": question, "database": database},
                    timeout=30
                )
                if response.status_code == 200:
                    st.json(response.json())
                else:
                    st.error(f"{t('api_error')}: {response.status_code} - {response.text}")
            except Exception as e:
                st.error(f"{t('connection_failed')}: {str(e)}")
    else:
        if st.button(t('test_connection_btn')):
            try:
                # 简单的健康检查
                response = {"status": t('api_service_normal'), "endpoint": test_endpoint}
                st.json(response)
            except Exception as e:
                st.error(f"{t('connection_failed')}: {str(e)}")