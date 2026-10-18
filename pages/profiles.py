from uuid import uuid4

import streamlit as st

from utils.config_manager import ConfigManager
from utils.i18n import t
from utils.profiles import validate_profile
from utils.run_context import snapshot_config
from utils.resource_scope import filter_source, visible

st.title(t("profiles_title"))
st.caption(t("profiles_help"))
config = ConfigManager()
profiles = config.load_profiles()
snapshot = snapshot_config(config, catalog=True)
if "saved_profile" in st.session_state:
    st.session_state["profile_editor"] = st.session_state.pop("saved_profile")
selected = st.selectbox(t("profile_edit"), ["__new__", *profiles], key="profile_editor",
                        format_func=lambda key: t("profile_new") if key == "__new__" else profiles[key]["name"])
current = profiles.get(selected, {})
if selected == "__new__" and st.session_state.get("new_profile_id") in profiles:
    st.session_state.pop("new_profile_id")
identifier = current.get("id") or st.session_state.setdefault("new_profile_id", uuid4().hex)
prefix = f"profile_{selected}"
name = st.text_input(t("profile_name"), current.get("name", ""), key=f"{prefix}_name")
description = st.text_area(t("profile_description"), current.get("description", ""), key=f"{prefix}_description")
if current:
    st.caption(f"ID: {selected}")
    try:
        validate_profile(current, snapshot)
    except ValueError as exc:
        st.error(str(exc))

st.subheader(t("profile_sources"))
sources = {key: filter_source(source, identifier) for key, source in snapshot["sources"].items()
           if visible(source, identifier)}
if not sources:
    st.info(t("configure_source_hint"))
source_ids = st.multiselect(t("active_sources"), list(sources),
                            default=[key for key in current.get("datasources", {}) if key in sources],
                            format_func=lambda key: f"{sources[key]['name']} ({sources[key]['engine']})",
                            key=f"{prefix}_sources")
bindings = {}
for source_id in source_ids:
    source = sources[source_id]
    tables = source["schema"].get("tables", {})
    bindings[source_id] = st.multiselect(
        f"{source['name']} · {t('profile_tables')}", list(tables),
        default=[table for table in current.get("datasources", {}).get(source_id, []) if table in tables],
        key=f"{prefix}_tables_{source_id}", help=t("profile_tables_help"))
    if not tables:
        st.warning(t("profile_schema_required"))

st.subheader(t("profile_resources"))
servers = snapshot["mcp"]
server_ids = st.multiselect(t("profile_servers"), list(servers),
                            default=[key for key in current.get("mcp_servers", []) if key in servers],
                            format_func=lambda key: f"{key} · {servers[key].get('status', 'inactive')}",
                            key=f"{prefix}_servers", help=t("profile_servers_help"))
docs = {doc["id"]: doc for doc in snapshot["knowledge"].get("documents", []) if visible(doc, identifier)}
knowledge_ids = st.multiselect(t("profile_knowledge"), list(docs),
                               default=[key for key in current.get("knowledge_ids", []) if key in docs],
                               format_func=lambda key: f"{docs[key]['scope']} / {docs[key]['title']}",
                               key=f"{prefix}_knowledge", help=t("profile_empty_resources"))
methods = {method["id"]: method for method in snapshot["methods"].get("methods", []) if visible(method, identifier)}
method_ids = st.multiselect(t("profile_methods"), list(methods),
                            default=[key for key in current.get("method_ids", []) if key in methods],
                            format_func=lambda key: f"{methods[key]['title']} · {t(methods[key]['status'])}",
                            key=f"{prefix}_methods", help=t("profile_methods_help"))
queries = {item["id"]: item for item in snapshot["query_knowledge"].get("queries", []) if visible(item, identifier)}
query_ids = st.multiselect(t("query_knowledge_title"), list(queries),
                           default=[key for key in current.get("query_ids", []) if key in queries],
                           format_func=lambda key: queries[key]["question"], key=f"{prefix}_queries",
                           help=t("query_links_help"))
draft = st.checkbox(t("profile_draft"), value=current.get("status", "draft" if not current else "active") == "draft",
                     key=f"{prefix}_draft")
st.info(t("profile_model_hint"))
st.caption(f"{len(source_ids)} {t('profile_connections_count')} · "
           f"{sum(len(tables) for tables in bindings.values())} {t('profile_tables')} · "
           f"{len(server_ids)} MCP/RPC · {len(knowledge_ids)} {t('profile_knowledge')}")
if st.button(t("save_profile"), type="primary"):
    try:
        config.save_profile({**current, "id": identifier, "name": name, "description": description,
                             "datasources": bindings, "mcp_servers": server_ids,
                             "knowledge_ids": knowledge_ids, "method_ids": method_ids, "query_ids": query_ids,
                             "status": "draft" if draft else "active"})
        st.session_state["saved_profile"] = identifier
        st.session_state["profile_saved_notice"] = True
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))
if st.session_state.pop("profile_saved_notice", False):
    st.success(t("config_saved"))
if current:
    consent = st.checkbox(t("profile_delete_help"), key=f"{prefix}_delete")
    if st.button(t("delete"), disabled=not consent):
        try:
            config.delete_profile(selected)
            st.session_state["saved_profile"] = "__new__"
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
