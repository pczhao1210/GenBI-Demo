import streamlit as st
import copy
import hashlib
import json
from utils.config_manager import ConfigManager
from utils.mcp_client import MCPClient
from utils.i18n import t
from utils.datasources import DatabaseAdapter
from utils.profile_ui import ui_config, visibility_editor, writing_example

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

config_manager = ui_config()
mcp_client = MCPClient(config_manager)
writing_example("schema", t("schema_writing_example"))

# 数据库选择
sources = config_manager.load_datasources()
database = st.selectbox(t('select_database'), list(sources),
                        format_func=lambda key: sources[key]["name"])
if not database:
    st.info(t("configure_source_hint"))
    st.stop()

# 获取数据库配置
datasource = sources[database]
db_config = datasource["config"]
engine = datasource["engine"]
adapter = DatabaseAdapter(datasource, mcp_client)

if not db_config:
    st.warning(t('config_db_connection_first').format(db_type=database.upper()))
    st.stop()

source = f"{config_manager.profile_id or 'shared'}:{database}:" + hashlib.sha256(json.dumps(db_config, sort_keys=True).encode()).hexdigest()
editors = st.session_state.setdefault("schema_editors", {})
if source not in editors:
    schema_config = config_manager.load_schema_config().get(database, {})
    editors[source] = {
        "tables": list(schema_config.get("tables", {})), "fields": {
            table: copy.deepcopy(info.get("columns", []) if isinstance(info, dict) else info)
            for table, info in schema_config.get("tables", {}).items()
        },
        "descriptions": copy.deepcopy(schema_config.get("descriptions", {})),
        "table_scopes": copy.deepcopy(schema_config.get("table_scopes", {})), "revision": 0,
    }
editor = editors[source]
st.session_state.tables = editor["tables"]
st.session_state.table_fields = editor["fields"]
st.session_state.table_descriptions = editor["descriptions"]
widget_prefix = f"{source}_{editor['revision']}"

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader(t('table_list'))
    with st.expander(t("manual_table_schema")):
        st.caption(t("schema_edit_only"))
        new_table = st.text_input(t("table_name"), key=f"{source}_new_table").strip()
        if st.button(t("add_table_schema"), key=f"{source}_add_table"):
            existing = [item["name"] if isinstance(item, dict) else item for item in editor["tables"]]
            if not new_table or new_table in existing:
                st.error(t("schema_unique_table"))
            elif not config_manager.table_visible(database, new_table):
                st.error(t("schema_unavailable_table"))
            else:
                editor["tables"] = existing + [new_table]
                editor["fields"][new_table] = []
                editor["selected_table"] = new_table
                st.rerun()
    
    if st.button(t('refresh_schema')):
        with st.spinner("正在获取表列表..."):
            try:
                tables = (mcp_client.get_tables(engine, db_config) if engine in ("mysql", "athena")
                          else adapter.metadata()["tables"])
                tables = [table for table in tables if config_manager.table_visible(
                    database, table.get("name", str(table)) if isinstance(table, dict) else table)]
                names = [item["name"] if isinstance(item, dict) else item for item in tables]
                editor["tables"] = st.session_state.tables = list(dict.fromkeys([*names, *editor["fields"]]))
                st.success(f"已获取{len(tables)}个表")
            except RuntimeError as exc:
                st.error(str(exc))
    
    if st.session_state.tables:
        # 检查tables是字典列表还是字符串列表
        if st.session_state.tables and isinstance(st.session_state.tables[0], dict):
            # 如果是字典列表，提取表名
            table_names = [table.get('name', str(table)) for table in st.session_state.tables]
            selected_table = st.selectbox(t('select_table'), table_names,
                                          key=f"{source}_table")
            
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
            if "selected_table" in editor:
                st.session_state[f"{source}_table"] = editor.pop("selected_table")
            if st.session_state.get(f"{source}_table") not in st.session_state.tables:
                st.session_state.pop(f"{source}_table", None)
            selected_table = st.selectbox(t('select_table'), st.session_state.tables, key=f"{source}_table")
    else:
        st.info(t('click_refresh_schema'))
        selected_table = None

with col2:
    if selected_table:
        st.subheader(f"{t('table_details')}: {selected_table}")
        table_scope = visibility_editor(
            editor["table_scopes"].get(selected_table, {}), f"{widget_prefix}_{selected_table}",
            config_manager.profile_id, new=selected_table not in datasource["schema"].get("tables", {}))
        editor["table_scopes"][selected_table] = table_scope
        st.caption(t("table_scope_help"))
        
        # 表描述
        description = st.text_area(
            t('table_description'), value=st.session_state.table_descriptions.get(selected_table, ""),
            key=f"{widget_prefix}_{selected_table}_description",
        )
        st.session_state.table_descriptions[selected_table] = description
        
        # 获取表字段
        if st.button(t('get_field_info')):
            with st.spinner("正在获取表结构..."):
                try:
                    # 如果表名与数据库名相同，可能需要特殊处理
                    if engine == "athena" and selected_table == db_config.get("database"):
                        st.info(f"注意: 表名与数据库名相同 ({selected_table})")
                    
                    # 尝试直接查询表结构
                    fields = (mcp_client.describe_table(engine, db_config, selected_table)
                              if engine in ("mysql", "athena") else adapter.metadata(selected_table)["columns"])
                    
                    if fields:
                        old_names = {field["name"] for field in st.session_state.table_fields.get(selected_table, [])}
                        new_names = {field["name"] for field in fields}
                        if old_names:
                            st.info(f"{t('schema_diff')}: +{sorted(new_names - old_names)} / -{sorted(old_names - new_names)}")
                        previous_fields = {field["name"]: field
                                           for field in st.session_state.table_fields.get(selected_table, [])}
                        for field in fields:
                            previous = previous_fields.get(field["name"], {})
                            for key in ("comment", "business_key"):
                                if key in previous:
                                    field[key] = previous[key]
                        st.session_state.table_fields[selected_table] = fields
                        st.success(f"已获取{len(fields)}个字段")
                    else:
                        # 如果失败，尝试直接查询表获取列信息
                        st.warning("尝试替代方法获取表结构...")
                        
                        # 执行查询获取列信息
                        query_result = {"result": adapter.preview(selected_table, 1)}
                        
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
            search_field = st.text_input(t("search_fields"), key=f"{widget_prefix}_search_{selected_table}")
            if st.button(t("preview_data"), key=f"{widget_prefix}_preview_{selected_table}"):
                try:
                    from utils.result_view import render_table
                    render_table(adapter.preview(selected_table)["data"], f"schema_{database}_{selected_table}")
                except (ValueError, RuntimeError) as exc:
                    st.error(str(exc))
            with st.expander(t("batch_descriptions")):
                import pandas as pd
                edits = st.data_editor(pd.DataFrame([
                    {"name": field["name"], "type": field.get("type", ""), "comment": field.get("comment", ""),
                     "business_key": bool(field.get("business_key", False))} for field in fields],
                    columns=["name", "type", "comment", "business_key"]),
                    num_rows="dynamic", hide_index=True, key=f"{widget_prefix}_batch_{selected_table}")
                st.caption(t("schema_edit_only"))
                if st.button(t("apply_descriptions"), key=f"{widget_prefix}_apply_{selected_table}"):
                    try:
                        updated = edits.astype(object).where(edits.notna(), None).to_dict("records")
                        for field in updated:
                            if isinstance(field["name"], str):
                                field["name"] = field["name"].strip()
                            field["type"] = field["type"] or ""
                            field["comment"] = field["comment"] or ""
                            field["business_key"] = bool(field["business_key"])
                        names = [field.get("name") for field in updated]
                        if (any(not isinstance(name, str) or not name.strip() for name in names)
                                or len(set(names)) != len(names)):
                            raise ValueError(t("schema_unique_fields"))
                        old_fields = {field["name"]: field for field in fields}
                        editor["fields"][selected_table] = [
                            {**old_fields.get(field["name"], {}), **field} for field in updated]
                        editor["revision"] += 1
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            
            for i, field in enumerate(fields):
                field_name = field.get("name", "")
                field_type = field.get("type", "")
                if search_field and search_field.lower() not in (
                        field_name + " " + field.get("comment", "")).lower():
                    continue
                
                with st.expander(f"{field_name} ({field_type})"):
                    # 显示原始信息
                    if engine == "mysql":
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
                        key=f"{widget_prefix}_desc_{selected_table}_{i}"
                    )
                    # 更新字段描述
                    if new_desc != field.get("comment", ""):
                        st.session_state.table_fields[selected_table][i]["comment"] = new_desc
        else:
            st.info(t('click_get_field_info'))
        consent = st.checkbox(t("delete_config_confirmation"), key=f"{widget_prefix}_{selected_table}_delete_confirm")
        if st.button(t("delete_table_schema"), disabled=not consent, key=f"{widget_prefix}_{selected_table}_delete"):
            try:
                remaining = {key: value for key, value in editor["fields"].items() if key != selected_table}
                descriptions = {key: value for key, value in editor["descriptions"].items() if key in remaining}
                scopes = {key: value for key, value in editor["table_scopes"].items() if key in remaining}
                config_manager.save_schema_config(database, {
                    "tables": remaining, "descriptions": descriptions, "table_scopes": scopes})
                editors.pop(source)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
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
                "descriptions": st.session_state.table_descriptions,
                "table_scopes": {key: value for key, value in editor["table_scopes"].items()
                                 if key in st.session_state.table_fields},
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
    clear_confirmed = st.checkbox(t("delete_config_confirmation"), key=f"{widget_prefix}_clear_confirm")
    if st.button("🗑️ 清空配置", disabled=not clear_confirmed):
        try:
            config_manager.save_schema_config(database, {"tables": {}, "descriptions": {}, "table_scopes": {}})
            editors.pop(source)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

# 显示已保存的配置
if st.checkbox(t('show_saved_schema')):
    saved_config = config_manager.load_schema_config()
    if saved_config:
        st.json(saved_config)
    else:
        st.info(t('no_saved_config'))