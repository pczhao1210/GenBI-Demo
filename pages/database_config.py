import streamlit as st
from utils.config_manager import ConfigManager
from utils.mcp_client import MCPClient
from utils.i18n import t, language_selector

st.set_page_config(page_title="Database Configuration", page_icon="🗄️")
st.title(f"🗄️ {t('database_config')}")

# 全局语言支持 - 不需要在子页面显示选择器

config_manager = ConfigManager()
mcp_client = MCPClient()
db_config = config_manager.load_database_config()

# 数据库类型选择
db_type = st.selectbox(t('select_database_type'), ["athena", "mysql"])

st.subheader(t('db_config_header').format(db_type=db_type.upper()))

if db_type == "athena":
    region = st.text_input("AWS Region", value=db_config.get("athena", {}).get("region", "us-east-1"))
    use_s3_output = st.checkbox(t('use_s3_output'), value=False)
    s3_output = ""
    if use_s3_output:
        s3_output = st.text_input("S3 Output Location", value=db_config.get("athena", {}).get("s3_output_location", ""))
    database = st.text_input("Database", value=db_config.get("athena", {}).get("database", "default"))
    access_key = st.text_input("AWS Access Key", value=db_config.get("athena", {}).get("aws_access_key_id", ""))
    secret_key = st.text_input("AWS Secret Key", value=db_config.get("athena", {}).get("aws_secret_access_key", ""), type="password")
    max_rows = st.number_input(t('max_rows'), min_value=1, max_value=10000, value=db_config.get("athena", {}).get("max_rows", 100))

else:  # mysql
    host = st.text_input("Host", value=db_config.get("mysql", {}).get("host", "localhost"))
    port = st.number_input("Port", min_value=1, max_value=65535, value=db_config.get("mysql", {}).get("port", 3306))
    database = st.text_input("Database", value=db_config.get("mysql", {}).get("database", ""))
    username = st.text_input("Username", value=db_config.get("mysql", {}).get("username", ""))
    password = st.text_input("Password", value=db_config.get("mysql", {}).get("password", ""), type="password")
    max_rows = st.number_input(t('max_rows'), min_value=1, max_value=10000, value=db_config.get("mysql", {}).get("max_rows", 100))

# 按钮操作
col1, col2 = st.columns(2)
with col1:
    if st.button(t('test_connection'), type="secondary"):
        with st.spinner(t('testing_connection')):
            # 构建测试配置
            if db_type == "athena":
                test_config = {
                    "region": region,
                    "database": database,
                    "aws_access_key_id": access_key,
                    "aws_secret_access_key": secret_key,
                    "max_rows": max_rows
                }
                # 只有当选择使用S3输出位置时才添加该参数
                if use_s3_output and s3_output:
                    test_config["s3_output_location"] = s3_output
            else:
                test_config = {
                    "host": host,
                    "port": port,
                    "database": database,
                    "username": username,
                    "password": password,
                    "max_rows": max_rows
                }
            
            # 测试连接
            try:
                # 使用新的方法直接在一个请求中初始化并获取表列表
                tables_result = mcp_client.call_mcp_server_with_config(
                    db_type, 
                    "get_tables", 
                    test_config, 
                    {"database": database}
                )
                
                if "error" in tables_result:
                    st.error(f"连接测试失败: {tables_result['error']}")
                elif "result" in tables_result and isinstance(tables_result["result"], dict) and "success" in tables_result["result"] and tables_result["result"]["success"]:
                    tables = tables_result["result"].get("tables", [])
                    table_count = len(tables)
                    st.success(f"数据库连接成功！发现 {table_count} 个表")
                    
                    # 如果没有找到表，尝试直接查询数据库同名表
                    if table_count == 0 and db_type == "athena":
                        st.info(f"正在尝试查询数据库同名表 '{database}'...")
                        
                        # 尝试查询数据库同名表
                        query_result = mcp_client.call_mcp_server_with_config(
                            db_type,
                            "execute_query",
                            test_config,
                            {"sql": f"SELECT * FROM {database} LIMIT 10", "database": database}
                        )
                        
                        if "error" in query_result:
                            st.error(f"查询表失败: {query_result['error']}")
                            
                            # 如果查询失败，尝试查询defects表
                            st.info("正在尝试查询 'defects' 表...")
                            query_result = mcp_client.call_mcp_server_with_config(
                                db_type,
                                "execute_query",
                                test_config,
                                {"sql": "SELECT * FROM defects LIMIT 10", "database": database}
                            )
                            
                            if "error" not in query_result and "result" in query_result and query_result["result"].get("success"):
                                st.success("成功查询到表 'defects'！")
                                # 显示表结构
                                if "data" in query_result["result"]:
                                    columns = query_result["result"]["data"].get("columns", [])
                                    rows = query_result["result"]["data"].get("rows", [])
                                    st.write(f"表列信息 ({len(columns)} 列):")
                                    st.write(columns)
                                    st.write(f"数据示例 ({len(rows)} 行):")
                                    st.dataframe(rows)
                            else:
                                # 允许用户手动输入表名
                                st.warning("未找到默认表，请手动输入表名进行测试。")
                                test_table = st.text_input("输入表名进行测试")
                                
                                if test_table and st.button("测试表连接"):
                                    with st.spinner(f"正在测试表 {test_table}..."):
                                        query_result = mcp_client.call_mcp_server_with_config(
                                            db_type,
                                            "execute_query",
                                            test_config,
                                            {"sql": f"SELECT * FROM {test_table} LIMIT 10", "database": database}
                                        )
                                        
                                        if "error" in query_result:
                                            st.error(f"查询表失败: {query_result['error']}")
                                        elif "result" in query_result and query_result["result"].get("success"):
                                            st.success(f"成功查询到表 '{test_table}'！")
                                            if "data" in query_result["result"]:
                                                columns = query_result["result"]["data"].get("columns", [])
                                                rows = query_result["result"]["data"].get("rows", [])
                                                st.write(f"表列信息 ({len(columns)} 列):")
                                                st.write(columns)
                                                st.write(f"数据示例 ({len(rows)} 行):")
                                                st.dataframe(rows)
                        else:
                            # 查询成功，显示结果
                            st.success(f"成功查询到表 '{database}'！")
                            if "data" in query_result["result"]:
                                columns = query_result["result"]["data"].get("columns", [])
                                rows = query_result["result"]["data"].get("rows", [])
                                st.write(f"表列信息 ({len(columns)} 列):")
                                st.write(columns)
                                st.write(f"数据示例 ({len(rows)} 行):")
                                st.dataframe(rows)
                else:
                    st.warning("连接成功，但无法获取表列表")
                        
            except Exception as e:
                st.error(f"连接测试出错: {str(e)}")

with col2:
    if st.button(t('save_config'), type="primary"):
        if db_type == "athena":
            new_config = {
                "region": region,
                "database": database,
                "aws_access_key_id": access_key,
                "aws_secret_access_key": secret_key,
                "max_rows": max_rows
            }
            # 只有当选择使用S3输出位置时才添加该参数
            if use_s3_output and s3_output:
                new_config["s3_output_location"] = s3_output
        else:
            new_config = {
                "host": host,
                "port": port,
                "database": database,
                "username": username,
                "password": password,
                "max_rows": max_rows
            }
        
        config_manager.save_database_config(db_type, new_config)
        st.success(t('config_saved'))