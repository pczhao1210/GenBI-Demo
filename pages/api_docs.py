import streamlit as st
import requests

st.set_page_config(page_title="API文档", page_icon="📚")
st.title("📚 API接口文档")

# API服务状态
st.subheader("🔍 服务状态")
col1, col2 = st.columns(2)

with col1:
    try:
        # TODO: 实际检查API状态
        backend_status = "🟢 运行中"
    except:
        backend_status = "🔴 离线"
    st.metric("Backend API", backend_status)

with col2:
    try:
        # 检查API服务状态
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            api_status = "🟢 正常"
        else:
            api_status = "🟡 异常"
    except:
        api_status = "🔴 离线"
    st.metric("API服务", api_status)

# API端点列表
st.subheader("📋 API端点")

endpoints = [
    {"method": "POST", "path": "/query", "description": "执行数据查询"},
    {"method": "POST", "path": "/analyze", "description": "执行数据分析"},
    {"method": "POST", "path": "/optimize-chain", "description": "优化分析链"},
    {"method": "POST", "path": "/generate-sql", "description": "生成SQL查询语句（系统集成）", "highlight": True},
    {"method": "GET", "path": "/health", "description": "服务健康检查"}
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
st.subheader("📖 详细文档")
col1, col2 = st.columns(2)

with col1:
    if st.button("🔗 Swagger UI文档", type="primary"):
        st.markdown("[Swagger UI](http://localhost:8000/docs) - 在新标签页中打开")

with col2:
    if st.button("🧪 API测试工具", type="secondary"):
        st.markdown("[ReDoc文档](http://localhost:8000/redoc) - 在新标签页中打开")

# 新增API介绍
st.subheader("✨ 新增功能")
with st.expander("🆕 /generate-sql - SQL生成API"):
    st.markdown("""
    **功能**: 根据自然语言问题生成SQL查询语句
    
    **请求示例**:
    ```json
    {
        "question": "显示前10行数据",
        "database": "athena"
    }
    ```
    
    **响应示例**:
    ```json
    {
        "sql": "SELECT * FROM table_name LIMIT 10",
        "success": true,
        "error": null
    }
    ```
    
    **使用场景**: 系统集成、自动化查询生成
    """)

# API测试区域
st.subheader("🧪 API测试")
with st.expander("快速测试API"):
    test_endpoint = st.selectbox("选择端点", [ep["path"] for ep in endpoints])
    
    if test_endpoint == "/generate-sql":
        st.markdown("**测试SQL生成API**")
        question = st.text_input("输入查询问题", value="显示前10行数据")
        database = st.selectbox("数据库类型", ["athena", "mysql"])
        
        if st.button("生成SQL"):
            try:
                response = requests.post(
                    "http://localhost:8000/generate-sql",
                    json={"question": question, "database": database},
                    timeout=30
                )
                if response.status_code == 200:
                    st.json(response.json())
                else:
                    st.error(f"API错误: {response.status_code} - {response.text}")
            except Exception as e:
                st.error(f"连接失败: {str(e)}")
    else:
        if st.button("测试连接"):
            try:
                # 简单的健康检查
                response = {"status": "API服务正常", "endpoint": test_endpoint}
                st.json(response)
            except Exception as e:
                st.error(f"连接失败: {str(e)}")