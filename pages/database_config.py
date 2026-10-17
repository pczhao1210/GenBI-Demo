from uuid import uuid4

import streamlit as st

from utils.config_manager import ConfigManager
from utils.datasources import DatabaseAdapter, ENGINES
from utils.i18n import t
from utils.mcp_client import MCPClient

st.set_page_config(page_title="Data sources", page_icon="🗄️")
st.title(t("database_config"))
config = ConfigManager()
sources = config.load_datasources()
engine = st.selectbox(t("select_database"), ENGINES)
candidates = [key for key, value in sources.items() if value["engine"] == engine]
selection_key = f"source_connection_{engine}"
saved_key = f"saved_source_{engine}"
saved_id = st.session_state.pop(saved_key, None)
if saved_id in candidates:
    st.session_state[selection_key] = saved_id
    st.success(t("config_saved"))
selection = st.selectbox(t("source_connection"), [*candidates, "__new__"],
                         format_func=lambda key: t("new_connection") if key == "__new__" else sources[key]["name"],
                         key=selection_key)
if selection == "__new__":
    draft_key = f"new_source_{engine}"
    if st.session_state.get(draft_key) in sources:
        st.session_state.pop(draft_key)
    key = st.session_state.setdefault(draft_key, uuid4().hex[:12])
    source = {"datasource_id": key, "name": engine, "engine": engine, "config": {}, "schema": {}}
else:
    source = sources[selection]
prefix = f"{source['datasource_id']}_"
current = source["config"]


def field(label, name, default="", password=False):
    return st.text_input(t(label), value=str(current.get(name, default)), type="password" if password else "default",
                         key=prefix + name)


name = st.text_input(t("connection_name"), value=source["name"], key=prefix + "name")
st.caption(f"datasource_id: {source['datasource_id']}")
connection = {}
if engine == "athena":
    for label, default in (("region", "us-east-1"), ("database", "default"), ("catalog", "AwsDataCatalog"),
                           ("workgroup", "primary"), ("s3_output_location", "")):
        connection[label] = field(label, label, default)
    for label in ("aws_access_key_id", "aws_secret_access_key", "aws_session_token"):
        connection[label] = field(label, label, password=True)
else:
    for label, default in (("host", "localhost"), ("database", ""), ("username", "")):
        connection[label] = field(label, label, default)
    connection["password"] = field("password", "password", password=True)
    connection["port"] = st.number_input(t("port"), 1, 65535, int(current.get(
        "port", {"mysql": 3306, "postgresql": 5432, "mssql": 1433}[engine])), key=prefix + "port")
    if engine == "mysql":
        modes = ["禁用SSL", "系统CA证书", "自定义证书", "强制SSL"]
        mode = st.selectbox(t("ssl_mode_label"), modes,
                            index=modes.index(current["ssl_mode"]) if current.get("ssl_mode") in modes else 1,
                            key=prefix + "ssl")
        connection.update(ssl_mode=mode, use_ssl=mode != modes[0], verify_ssl=mode in modes[1:3])
        if mode == modes[2]:
            for label in ("ssl_ca", "ssl_cert", "ssl_key"):
                connection[label] = field(label, label)
    else:
        connection["schema"] = field("schema_name", "schema", "public" if engine == "postgresql" else "dbo")
    if engine == "mssql":
        connection["driver"] = field("odbc_driver", "driver", "ODBC Driver 18 for SQL Server")
        connection["encrypt"] = field("encrypt", "encrypt", "yes")
        connection["trust_server_certificate"] = field("trust_certificate", "trust_server_certificate", "no")
        st.info(t("odbc_notice"))
connection["max_rows"] = st.number_input(t("row_limit"), 1, 10000, int(current.get("max_rows", 1000)),
                                          key=prefix + "rows")
connection["query_timeout"] = st.number_input(t("query_timeout_label"), 1, 600,
                                               int(current.get("query_timeout", 30)), key=prefix + "timeout")
connection["connection_timeout"] = int(current.get("connection_timeout", 10))
timezone = st.text_input(t("business_timezone"), value=source.get("timezone", "UTC"), key=prefix + "timezone")
day_start = st.number_input(t("business_day_hour"), 0, 23, source.get("business_day_start", 0),
                           key=prefix + "day")
source = {**source, "name": name, "config": connection, "timezone": timezone, "business_day_start": day_start}
adapter = DatabaseAdapter(source, MCPClient(config))
left, right = st.columns(2)
try:
    if left.button(t("test_source")):
        st.json(adapter.metadata())
        st.success(t("connection_test_success"))
    if right.button(t("save_source"), type="primary"):
        config.save_datasource(source)
        if selection == "__new__":
            st.session_state.pop(draft_key, None)
            st.session_state[saved_key] = source["datasource_id"]
            st.rerun()
        st.success(t("config_saved"))
    if st.button(t("source_diagnostics")):
        st.json(adapter.diagnostics())
except (ValueError, RuntimeError) as exc:
    st.error(str(exc))
