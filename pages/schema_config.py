import streamlit as st
from utils.config_manager import ConfigManager
from utils.mcp_client import MCPClient

st.set_page_config(page_title="Schema配置", page_icon="📋")
st.title("📋 数据库Schema配置")

config_manager = ConfigManager()
mcp_client = MCPClient()

# 数据库选择
database = st.selectbox("选择数据库", ["mysql", "athena"])

# 获取数据库配置
db_config = config_manager.load_database_config().get(database, {})

if not db_config:
    st.warning(f"请先在数据库配置页面配置{database.upper()}连接信息")
    st.stop()

# 初始化session state
if "tables" not in st.session_state:
    st.session_state.tables = []
if "table_fields" not in st.session_state:
    st.session_state.table_fields = {}
if "table_descriptions" not in st.session_state:
    st.session_state.table_descriptions = {}

# 加载已保存的schema配置
schema_config = config_manager.load_schema_config().get(database, {})
if schema_config:
    st.session_state.table_fields.update(schema_config.get("tables", {}))
    st.session_state.table_descriptions.update(schema_config.get("descriptions", {}))

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("表列表")
    
    if st.button("刷新Schema"):
        with st.spinner("正在获取表列表..."):
            tables = mcp_client.get_tables(database, db_config)
            if tables:
                st.session_state.tables = tables
                st.success(f"已获取{len(tables)}个表")
            else:
                st.error("获取表列表失败，请检查数据库连接")
    
    if st.session_state.tables:
        selected_table = st.selectbox("选择表", st.session_state.tables)
    else:
        st.info("点击'刷新Schema'获取表列表")
        selected_table = None

with col2:
    if selected_table:
        st.subheader(f"表详情: {selected_table}")
        
        # 表描述
        description = st.text_area("表描述", value=st.session_state.table_descriptions.get(selected_table, ""))
        st.session_state.table_descriptions[selected_table] = description
        
        # 获取表字段
        if st.button("获取字段信息"):
            with st.spinner("正在获取表结构..."):
                try:
                    # 如果表名与数据库名相同，可能需要特殊处理
                    if database == "athena" and selected_table == db_config.get("database"):
                        st.info(f"注意: 表名与数据库名相同 ({selected_table})")
                    
                    # 尝试直接查询表结构
                    fields = mcp_client.describe_table(database, db_config, selected_table)
                    
                    if fields:
                        st.session_state.table_fields[selected_table] = fields
                        st.success(f"已获取{len(fields)}个字段")
                    else:
                        # 如果失败，尝试直接查询表获取列信息
                        st.warning("尝试替代方法获取表结构...")
                        
                        # 执行查询获取列信息
                        query_result = mcp_client.call_mcp_server_with_config(
                            database,
                            "execute_query",
                            db_config,
                            {"sql": f"SELECT * FROM {selected_table} LIMIT 1", "database": db_config.get("database")}
                        )
                        
                        if "result" in query_result and "data" in query_result["result"]:
                            # 从查询结果中提取列信息
                            columns = query_result["result"]["data"].get("columns", [])
                            fields = []
                            for col in columns:
                                fields.append({
                                    "name": col,
                                    "type": "unknown",
                                    "comment": ""
                                })
                            
                            if fields:
                                st.session_state.table_fields[selected_table] = fields
                                st.success(f"已获取{len(fields)}个字段 (从查询结果中提取)")
                            else:
                                st.error("无法获取表结构")
                        else:
                            st.error("获取表结构失败")
                except Exception as e:
                    st.error(f"获取表结构时出错: {str(e)}")
        
        # 显示字段列表
        if selected_table in st.session_state.table_fields:
            st.markdown("**字段列表:**")
            fields = st.session_state.table_fields[selected_table]
            
            for i, field in enumerate(fields):
                field_name = field.get("name", "")
                field_type = field.get("type", "")
                
                with st.expander(f"{field_name} ({field_type})"):
                    # 显示原始信息
                    if database == "mysql":
                        st.text(f"类型: {field.get('type', '')}")
                        st.text(f"允许NULL: {field.get('null', '')}")
                        st.text(f"键: {field.get('key', '')}")
                        st.text(f"默认值: {field.get('default', '')}")
                        st.text(f"额外: {field.get('extra', '')}")
                    else:  # athena
                        st.text(f"类型: {field.get('type', '')}")
                        st.text(f"注释: {field.get('comment', '')}")
                    
                    # 自定义描述
                    new_desc = st.text_input(
                        "自定义描述", 
                        value=field.get("comment", ""), 
                        key=f"desc_{selected_table}_{i}"
                    )
                    # 更新字段描述
                    if new_desc != field.get("comment", ""):
                        st.session_state.table_fields[selected_table][i]["comment"] = new_desc
        else:
            st.info("点击'获取字段信息'查看表结构")
    else:
        st.info("请先选择一个表")

if st.button("保存配置", type="primary"):
    try:
        # 构建配置数据
        schema_data = {
            "tables": st.session_state.table_fields,
            "descriptions": st.session_state.table_descriptions
        }
        
        # 保存到JSON文件
        config_manager.save_schema_config(database, schema_data)
        st.success(f"{database.upper()} Schema配置已保存到 config/schema_config.json")
    except Exception as e:
        st.error(f"保存失败: {str(e)}")

# 显示已保存的配置
if st.checkbox("显示已保存的Schema配置"):
    saved_config = config_manager.load_schema_config()
    if saved_config:
        st.json(saved_config)
    else:
        st.info("暂无已保存的配置")