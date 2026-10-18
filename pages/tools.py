import json
import sys
from copy import deepcopy

import streamlit as st

from utils.config_manager import ConfigManager
from utils.i18n import t
from utils.mcp_client import MCPClient
from utils.model_router import ToolBudget
from utils.semantics import KnowledgeIndex
from utils.tool_catalog import CATEGORIES, ToolCatalog
from utils.tool_execution import ToolInvoker
from utils.tool_management import TEMPLATES, ToolManagement
from utils.datasources import DatabaseAdapter, ENGINES
from utils.profile_ui import ui_config
from utils.run_context import FrozenConfig, snapshot_config


def category_label(identifier, settings):
    name = settings["categories"][identifier]
    return t(f"tools_category_{identifier}") if name == CATEGORIES.get(identifier) else name


def render_tools():
    st.set_page_config(page_title="Tools", page_icon="🛠️", layout="wide")
    st.title(t("tools_title"))
    st.info(t("tools_protocol_help"))
    config = ui_config()
    client = MCPClient(config)
    management = ToolManagement(config, client)
    settings = config.load_tools_config()
    catalog = ToolCatalog(config)
    servers = config.load_mcp_config()
    builtin, mcp_tab = st.tabs([t("tools_local"), t("tools_mcp")])
    with builtin:
        category = _category_filter(settings, "local")
        if category in ("all", "database"):
            _connectors(config, servers, management)
        if category in ("all", "knowledge"):
            st.page_link("pages/semantics.py", label=t("semantics_title"))
            st.caption(f"{t('index_status')}: {len(KnowledgeIndex(config.load_knowledge()).chunks)}")
        _tool_groups([tool for tool in catalog.list() if tool["backend"] != "mcp"], category, management, settings)
        with st.expander(t("builtin_adapters")):
            if st.button(t("tools_scan_builtin")):
                for name, info in client.discover_available_servers().items():
                    if name not in servers:
                        servers[name] = {"type": "stdio", "command": sys.executable,
                                         "args": [f"mcp_servers/{name}_server.py"], "status": "inactive",
                                         "description": info.get("description", ""), "capabilities": []}
                config.save_mcp_config(servers)
                st.rerun()
            for name, server in servers.items():
                if server.get("protocol") != "mcp" and name not in ("mysql", "athena"):
                    _server_card(name, server, management)
    with mcp_tab:
        category = _category_filter(settings, "mcp")
        notice = st.session_state.pop("mcp_connected", None)
        if notice is not None:
            st.success(f"{t('mcp_connected')}: {notice}")
        _add_server(management, settings, category)
        for name, server in servers.items():
            if server.get("protocol") != "mcp":
                continue
            tools = [tool for tool in catalog.list() if tool.get("server_id") == name]
            categories = set(server.get("categories", [])) | {c for tool in tools for c in tool["categories"]}
            if category != "all" and category not in categories:
                continue
            st.subheader(name)
            _server_card(name, server, management)
            _tool_groups(tools, category, management, settings)

    with st.expander(t("tools_categories")):
        category_id = st.text_input(t("tools_stable_id"), key="category_id")
        category_name = st.text_input(t("tools_display_name"), key="category_name")
        if st.button(t("tools_save_category")):
            try:
                if not category_id.strip() or not category_name.strip():
                    raise ValueError(t("tools_category_required"))
                settings["categories"][category_id] = category_name
                config.save_tools_config(settings)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if st.button(t("tools_remove_category")):
            try:
                if (any(category_id in tool["categories"] for tool in catalog.list())
                        or any(category_id in server.get("categories", []) for server in servers.values())):
                    raise ValueError(t("tools_category_in_use"))
                del settings["categories"][category_id]
                config.save_tools_config(settings)
                st.rerun()
            except (ValueError, KeyError) as exc:
                st.error(str(exc))


def _category_filter(settings, kind):
    return st.selectbox(t("tools_category"), ["all", *settings["categories"]], key=f"category_{kind}",
                         format_func=lambda value: t("tools_all") if value == "all" else category_label(value, settings))


def _connectors(config, servers, management):
    st.subheader(t("database_connectors"))
    st.caption(t("configured_not_connected"))
    sources = config.load_datasources()
    for engine in ENGINES:
        with st.container(border=True):
            st.write({"mysql": "MySQL", "athena": "AWS Athena", "postgresql": "PostgreSQL (PGSQL)",
                      "mssql": "Microsoft SQL Server (MSSQL)"}[engine])
            connections = [source for source in sources.values() if source["engine"] == engine]
            st.caption(", ".join(source["name"] for source in connections) or t("needs_configuration"))
            st.caption(t("native_connector") if engine in ("postgresql", "mssql") else t("rpc_connector"))
            left, right = st.columns(2)
            if left.button(t("configure_now"), key=f"configure_{engine}"):
                st.session_state["configure_engine"] = engine
                st.switch_page("pages/database_config.py")
            if right.button(t("connector_diagnostics"), key=f"diagnostics_{engine}"):
                try:
                    source = {"engine": engine, "config": connections[0]["config"] if connections else {}}
                    st.json(DatabaseAdapter(source).diagnostics())
                except RuntimeError as exc:
                    st.error(str(exc))
            if engine in servers and servers[engine].get("protocol") != "mcp":
                _server_card(engine, servers[engine], management)


def _tool_groups(tools, category, management, settings):
    visible = [tool for tool in tools if category == "all" or category in tool["categories"]]
    groups = {}
    for tool in visible:
        group = category if category != "all" else next(iter(tool["categories"]), "uncategorized")
        groups.setdefault(group, []).append(tool)
    for group, tools in groups.items():
        st.subheader(category_label(group, settings) if group in settings["categories"] else t("uncategorized"))
        for tool in tools:
            _tool_card(tool, management, settings)
    if not visible:
        st.info(t("tools_empty_category"))

def _add_server(management, settings, category):
    with st.expander(t("add_mcp_server"), expanded=True):
        template = st.selectbox(t("tools_template"), list(TEMPLATES))
        defaults = deepcopy(TEMPLATES[template])
        server_id = st.text_input(t("server_name"), key=f"server_name_{template}")
        categories = st.multiselect(t("tools_category"), list(settings["categories"]),
                                   default=([category] if category != "all" else defaults["categories"] or ["external_api"]),
                                   key=f"server_categories_{template}",
                                   format_func=lambda value: category_label(value, settings))
        when = st.text_input(t("tools_when"), defaults["when_to_use"], key=f"when_{template}")
        if defaults["type"] == "stdio":
            command = st.text_input(t("command"), defaults["command"], key=f"command_{template}")
            args = st.text_area(t("tools_args_json"), json.dumps(defaults["args"]), key=f"args_{template}")
            cwd = st.text_input(t("tools_cwd"), key=f"cwd_{template}")
            env = st.text_area(t("tools_env_refs"), "{}", key=f"env_{template}")
        else:
            url = st.text_input(t("tools_endpoint"), defaults["url"], key=f"url_{template}")
            headers = st.text_area(t("tools_header_refs"), "{}", key=f"headers_{template}")
        with st.expander(t("tools_optional_mapping")):
            mapping = st.text_area(t("tools_capability_mapping"), json.dumps(defaults["capabilities"]),
                                   key=f"mapping_{template}")
            st.caption(t("tools_automatic_capabilities"))
        confirmed = st.checkbox(t("tools_probe_consent"), key=f"connect_consent_{template}")
        connect = st.button(t("mcp_connect_discover"), type="primary", key=f"connect_{template}", disabled=not confirmed)
        save = st.button(t("tools_save_disabled"), key=f"save_new_{template}")
        if connect or save:
            try:
                defaults.update(categories=categories, when_to_use=when, capabilities=json.loads(mapping))
                if defaults["type"] == "stdio":
                    defaults.update(command=command, args=json.loads(args), env_refs=json.loads(env))
                    if cwd:
                        defaults["cwd"] = cwd
                else:
                    defaults.update(url=url, header_refs=json.loads(headers))
                if connect:
                    info = management.connect_server(server_id, defaults, confirmed=confirmed)
                    st.session_state["mcp_connected"] = len(info.get("tools", []))
                else:
                    management.save_server(server_id, defaults)
                st.rerun()
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))


def _server_card(name, server, management):
    with st.expander(f"{name} · {server.get('status')}", expanded=False):
        protocol = "MCP" if server.get("protocol") == "mcp" else "legacy RPC"
        st.write(f"{name} · {protocol} · {server.get('type')} · {server.get('status')}")
        st.caption(t("tools_probe_not_connection"))
        st.caption(f"{t('tools_affected')}: {', '.join(server.get('capabilities', []))}")
        confirmed = st.checkbox(t("tools_probe_consent"), key=f"confirm_probe_{name}")
        if st.button(t("tools_check_status"), key=f"check_{name}"):
            try:
                info = management.discover(name, confirmed=confirmed)
                st.session_state[f"probe_{name}"] = {
                    key: value for key, value in info.items() if key != "tools"}
                st.success(t("tools_discovery_ok"))
                st.rerun()
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
        if st.session_state.get(f"probe_{name}"):
            st.json(st.session_state[f"probe_{name}"])
        for suffix, label, enabled in (("start", "enable_on_demand", True), ("stop", "disable_server", False)):
            if st.button(t(label), key=f"{suffix}_{name}"):
                try:
                    management.set_server_enabled(name, enabled)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        if server.get("protocol") == "mcp":
            _edit_server(name, server, management)
        consent = st.checkbox(t("tools_delete_consent"), key=f"delete_consent_{name}")
        if st.button(t("delete"), key=f"delete_{name}", disabled=not consent):
            management.delete_server(name)
            st.rerun()


def _edit_server(name, server, management):
    with st.expander(t("tools_edit_server")):
        editable = {key: value for key, value in server.items() if key not in ("status", "env", "headers", "auth")}
        raw = st.text_area(t("tools_server_json"), json.dumps(editable, ensure_ascii=False, indent=2),
                           key=f"server_edit_{name}")
        if st.button(t("tools_save_disabled"), key=f"save_server_{name}"):
            try:
                management.save_server(name, json.loads(raw), replace=True)
                st.rerun()
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))


def _tool_card(tool, management, settings):
    tool_id = tool["tool_id"]
    with st.expander(f"{tool_id} · {t('configured') if tool['enabled'] else t('tools_disabled')}"):
        enabled = st.toggle(t("tools_enabled"), tool["enabled"], key=f"enabled_{tool_id}")
        if enabled != tool["enabled"]:
            try:
                management.update_tool(tool_id, {"enabled": enabled})
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        st.write(tool["description"])
        if not tool["policy"]["read_only"] and tool["output_kind"] != "interpretation":
            st.warning(t("tool_readonly_required"))
        st.caption(f"{tool['backend']} · " + ", ".join(category_label(c, settings) for c in tool["categories"])
                   + f" · {', '.join(tool['capabilities'])}")
        if not tool["available"]:
            st.warning(tool["unavailable_reason"])
        if tool.get("discovered_at"):
            st.caption(tool["discovered_at"])
        if st.checkbox(t("debug_details"), key=f"schema_{tool_id}"):
            st.json({"input_schema": tool["input_schema"], "output_kind": tool["output_kind"],
                     "policy": tool["policy"], "definition_version": tool["definition_version"]})
        with st.form(f"tool_form_{tool_id}"):
            categories = st.multiselect(t("tools_category"), list(settings["categories"]),
                                       default=[c for c in tool["categories"] if c in settings["categories"]],
                                       format_func=lambda value: category_label(value, settings))
            when = st.text_input(t("tools_when"), tool["when_to_use"])
            read_only = st.checkbox(t("tools_read_only"), tool["policy"]["read_only"])
            timeout = st.number_input(t("query_timeout_label"), 1, 300, int(tool["policy"]["timeout"]))
            concurrency = st.number_input(t("tools_concurrency"), 1, 300, int(tool["policy"]["concurrency"]),
                                          disabled=tool["output_kind"] == "interpretation")
            if st.form_submit_button(t("save_config")):
                try:
                    management.update_tool(tool_id, {"enabled": enabled, "categories": categories,
                                                    "when_to_use": when, "policy": {
                                                        "read_only": read_only, "timeout": timeout,
                                                        "concurrency": concurrency}})
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        for capability in tool["capabilities"]:
            if st.button(f"{t('tools_default_provider')}: {capability}", key=f"default_{tool_id}_{capability}"):
                try:
                    management.set_default(capability, tool_id)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        if tool["backend"] == "local" and tool["tool_name"].startswith("compute."):
            st.caption(t("tools_compute_help"))
            st.warning(t("tools_demo_data"))
            if tool["enabled"] and st.button(t("tools_compute_demo"), key=f"demo_{tool_id}"):
                try:
                    parameters, inputs = _compute_demo(tool["tool_name"])
                    budget = ToolBudget(max_calls=1)
                    result = ToolInvoker(management.config, management.client, budget).call(
                        tool["tool_name"], parameters, tool_id, results=inputs)
                    st.json({"kind": "SAMPLE_CALCULATION", **result})
                    st.json(budget.records)
                except (ValueError, RuntimeError) as exc:
                    st.error(str(exc))
            return
        if (tool["output_kind"] == "interpretation" or not tool["enabled"] or not tool["available"]
                or not tool["capabilities"] or not tool["policy"]["read_only"]):
            return
        arguments = st.text_area(t("tools_trial_arguments"), "{}", key=f"trial_arguments_{tool_id}")
        if st.button(t("tools_trial"), key=f"trial_{tool_id}"):
            budget = ToolBudget(max_calls=4)
            try:
                scoped = FrozenConfig(snapshot_config(management.config.base, management.config.profile_id))
                invoker = ToolInvoker(scoped, management.client, budget)
                result = invoker.call(tool["capabilities"][0], json.loads(arguments), tool_id)
                st.json(result)
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
            finally:
                management.client.close()
            st.json(budget.records)


def _compute_demo(capability):
    def table(columns, rows, source):
        return {"status": "success", "data": {
            "columns": columns, "rows": rows, "row_count": len(rows), "completeness": "COMPLETE",
            "truncated": False, "entity": "sample", "grain": ["key"], "timezone": "UTC",
            "time_range": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"},
            "units": {column: "count" for column in columns if column != "key"},
            "datasource_id": source, "collected_at": "2026-01-02T00:00:00Z",
        }}
    if capability == "compute.join":
        return ({"inputs": [1, 2], "left_on": ["key"], "right_on": ["key"], "cardinality": "one_to_one"},
                {1: table(["key", "numerator"], [["A", "1.10"], ["B", "2.20"]], "SAMPLE_LEFT"),
                 2: table(["key", "denominator"], [["A", "3"], ["B", "7"]], "SAMPLE_RIGHT")})
    parameters = ({"columns": ["numerator"]} if capability == "compute.aggregate"
                  else {"numerator": "numerator", "denominator": "denominator"})
    return ({"inputs": [1], **parameters},
            {1: table(["key", "numerator", "denominator"],
                      [["A", "1.10", "3"], ["B", "2.20", "7"]], "SAMPLE_ALIGNED")})


if __name__ == "__main__":
    render_tools()
