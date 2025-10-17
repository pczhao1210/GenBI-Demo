import streamlit as st
from utils.config_manager import ConfigManager
from utils.mcp_client import MCPClient
from utils.i18n import t

st.set_page_config(page_title="Schema Configuration", page_icon="📋")
st.title(t('database_schema_config'))

# 多表配置工作流程说明
with st.expander("📚 多表Schema配置工作流程", expanded=False):
    st.markdown("""
    **🔄 推荐配置流程：**
    
    1. **刷新表列表** - 获取数据库中的所有表
    2. **逐表配置** - 选择每个表，依次进行配置：
       - 添加表描述信息
       - 获取表字段结构
       - 为重要字段添加自定义描述
    3. **一次性保存** - 配置完所有需要的表后，点击"保存所有表的Schema配置"
    
    **💡 提示：**
    - 可以配置多个表的schema信息，系统会保存所有表的配置
    - 每次选择不同的表时，之前配置的信息会自动保存到内存中
    - 最后点击保存按钮时，会将所有表的配置一次性写入文件
    """)

config_manager = ConfigManager()
mcp_client = MCPClient()

# 数据库选择
database = st.selectbox(t('select_database'), ["mysql", "athena"])

# 获取数据库配置
db_config = config_manager.load_database_config().get(database, {})

if not db_config:
    st.warning(t('config_db_connection_first').format(db_type=database.upper()))
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
    st.subheader(t('table_list'))
    
    if st.button(t('refresh_schema')):
        with st.spinner("正在获取表列表..."):
            tables = mcp_client.get_tables(database, db_config)
            if tables:
                st.session_state.tables = tables
                st.success(f"已获取{len(tables)}个表")
            else:
                st.error("获取表列表失败，请检查数据库连接")
    
    if st.session_state.tables:
        # 检查tables是字典列表还是字符串列表
        if st.session_state.tables and isinstance(st.session_state.tables[0], dict):
            # 如果是字典列表，提取表名
            table_names = [table.get('name', str(table)) for table in st.session_state.tables]
            selected_table = st.selectbox(t('select_table'), table_names)
            
            # 显示表的详细信息
            if selected_table:
                table_info = next((t for t in st.session_state.tables if t.get('name') == selected_table), None)
                if table_info:
                    if table_info.get('type'):
                        st.caption(f"类型: {table_info['type']}")
                    if table_info.get('comment'):
                        st.caption(f"注释: {table_info['comment']}")
                    if table_info.get('estimated_rows'):
                        st.caption(f"预估行数: {table_info['estimated_rows']:,}")
        else:
            # 如果是字符串列表，直接使用
            selected_table = st.selectbox(t('select_table'), st.session_state.tables)
    else:
        st.info(t('click_refresh_schema'))
        selected_table = None

with col2:
    if selected_table:
        st.subheader(f"{t('table_details')}: {selected_table}")
        
        # 表描述
        description = st.text_area(t('table_description'), value=st.session_state.table_descriptions.get(selected_table, ""))
        st.session_state.table_descriptions[selected_table] = description
        
        # 获取表字段
        if st.button(t('get_field_info')):
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
            st.markdown(f"**{t('field_list')}:**")
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
                        t('custom_description'), 
                        value=field.get("comment", ""), 
                        key=f"desc_{selected_table}_{i}"
                    )
                    # 更新字段描述
                    if new_desc != field.get("comment", ""):
                        st.session_state.table_fields[selected_table][i]["comment"] = new_desc
        else:
            st.info(t('click_get_field_info'))
    else:
        st.info(t('select_table_first'))

# 保存配置区域
st.divider()
st.subheader("💾 保存Schema配置")

# 显示当前待保存的配置统计
col1, col2 = st.columns(2)
with col1:
    table_count = len(st.session_state.table_fields)
    desc_count = len([desc for desc in st.session_state.table_descriptions.values() if desc.strip()])
    st.metric("已配置表结构", f"{table_count} 个表")
    
with col2:
    field_count = sum(len(fields) for fields in st.session_state.table_fields.values())
    st.metric("表描述", f"{desc_count} 个表有描述")

# 显示将要保存的表列表
if st.session_state.table_fields or st.session_state.table_descriptions:
    with st.expander("📋 查看待保存的配置", expanded=False):
        st.markdown("**将要保存的表配置：**")
        
        all_tables = set(st.session_state.table_fields.keys()) | set(st.session_state.table_descriptions.keys())
        for table_name in sorted(all_tables):
            with st.container():
                st.markdown(f"**• {table_name}**")
                
                # 显示表描述
                if table_name in st.session_state.table_descriptions and st.session_state.table_descriptions[table_name]:
                    st.caption(f"  📝 描述: {st.session_state.table_descriptions[table_name][:100]}...")
                
                # 显示字段信息
                if table_name in st.session_state.table_fields:
                    field_count = len(st.session_state.table_fields[table_name])
                    st.caption(f"  🏗️ 字段: {field_count} 个字段已配置")

# 保存和管理按钮
col1, col2 = st.columns([3, 1])

with col1:
    if st.button("💾 保存所有表的Schema配置", type="primary"):
        try:
            # 构建配置数据
            schema_data = {
                "tables": st.session_state.table_fields,
                "descriptions": st.session_state.table_descriptions
            }
            
            # 统计信息
            table_count = len(st.session_state.table_fields)
            desc_count = len([desc for desc in st.session_state.table_descriptions.values() if desc.strip()])
            field_count = sum(len(fields) for fields in st.session_state.table_fields.values())
            
            # 保存到JSON文件
            config_manager.save_schema_config(database, schema_data)
            
            # 显示详细的保存成功信息
            st.success(f"""
            ✅ **{database.upper()} Schema配置保存成功！**
            
            📊 **保存统计：**
            - 表结构配置: {table_count} 个表
            - 表描述: {desc_count} 个表
            - 字段配置: {field_count} 个字段
            - 保存位置: config/schema_config.json
            """)
        except Exception as e:
            st.error(f"❌ 保存失败: {str(e)}")

with col2:
    if st.button("🗑️ 清空配置"):
        st.session_state.table_fields.clear()
        st.session_state.table_descriptions.clear()
        st.success("✅ 已清空所有配置")
        st.rerun()

# 显示已保存的配置
if st.checkbox(t('show_saved_schema')):
    saved_config = config_manager.load_schema_config()
    if saved_config:
        st.json(saved_config)
    else:
        st.info(t('no_saved_config'))