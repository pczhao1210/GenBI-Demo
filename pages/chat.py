import hashlib
import json

import pandas as pd
import streamlit as st

from utils.bi_service import BIService, format_analysis_report
from utils.config_manager import ConfigManager
from utils.i18n import t
from utils.llm_client import LLMClient
from utils.test_question_helper import get_test_question_input, render_test_question_sidebar

st.set_page_config(page_title="Smart Chat", page_icon="💬", layout="wide")
st.title(t("smart_chat"))
config_manager = ConfigManager()

with st.sidebar:
    st.header(t("settings"))
    database = st.selectbox(t("select_database"), ["mysql", "athena"])
    db_config = config_manager.load_database_config().get(database, {})
    schema = config_manager.load_schema_config().get(database, {})
    llm_config = config_manager.load_llm_config()
    providers = ["openai", "azure_openai", "custom", "openai_sdk"]
    saved_provider = llm_config.get("provider", "openai")
    provider = st.selectbox(
        t("llm_provider"), providers,
        index=providers.index(saved_provider) if saved_provider in providers else 0,
    )
    llm_config = {**llm_config, "provider": provider}
    section = llm_config.get("openai" if provider == "openai_sdk" else provider, {})
    st.info(f"{t('current_using')}: {provider} - "
            f"{section.get('model', section.get('deployment_name', ''))}")
    show_schema = st.checkbox(t("show_schema_prompt"), value=True)
    use_llm = st.checkbox(t("use_llm_generate_sql"), value=True)
    st.caption(t("readonly_notice"))

service = BIService(config_manager, llm_client=LLMClient(llm_config))
source = hashlib.sha256(json.dumps(
    {"database": database, "connection": db_config, "schema": schema}, sort_keys=True,
).encode()).hexdigest()
sessions = st.session_state.setdefault("chat_sessions", {})
session = sessions.setdefault(source, {"messages": [], "plan": None, "question": None})
render_test_question_sidebar()

if not db_config:
    st.warning(t("config_db_connection_first").format(db_type=database.upper()))
if not schema.get("tables"):
    st.warning(t("config_schema_first").format(db_type=database.upper()))


def display_message(message):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("data") is not None:
            data = message["data"]
            st.dataframe(pd.DataFrame(data["rows"], columns=data["columns"]))
            if data.get("truncated"):
                st.warning(t("result_truncated"))
        if show_schema and message.get("schema_prompt"):
            with st.expander(t("show_schema_prompt"), expanded=False):
                st.text(message["schema_prompt"])


for message in session["messages"]:
    display_message(message)

execute = cancel = retry = False
if session["plan"] is not None:
    with st.expander(t("analysis_plan"), expanded=True):
        st.json(session["plan"], expanded=2)
    col1, col2 = st.columns(2)
    execute = col1.button(t("execute_plan"), type="primary")
    cancel = col2.button(t("cancel_plan"))
elif session.get("last_execution") and not session["last_execution"]["completed"]:
    retry = st.button(t("retry_plan"))

prompt = get_test_question_input() or st.chat_input(t("enter_question"))
if prompt:
    message = {"role": "user", "content": prompt}
    session["messages"].append(message)
    display_message(message)
    if session["plan"] is not None:
        execute = prompt.strip().lower() in ("执行", "开始", "execute", "run")
        cancel = prompt.strip().lower() in ("取消", "cancel")

if cancel:
    session.update(plan=None, question=None)
    st.rerun()

if retry:
    session["plan"] = session["last_execution"]["plan"]
    session["question"] = session["last_question"]
    execute = True

try:
    if execute:
        if not use_llm:
            raise ValueError(t("use_llm_generate_sql"))
        with st.spinner(t("thinking")):
            execution = service.execute_plan(session["plan"], session["question"], database)
        message = {"role": "assistant", "content": format_analysis_report(session["question"], execution)}
        session["messages"].append(message)
        session["last_execution"] = execution
        session["last_question"] = session["question"]
        session.update(plan=None, question=None)
        st.rerun()
    elif prompt and not cancel:
        if not use_llm:
            raise ValueError(t("use_llm_generate_sql"))
        service.database_config(database)
        service.schema(database)
        with st.spinner(t("thinking")):
            if session["plan"] is not None:
                session["plan"] = service.analysis_plan(
                    session["question"], database, previous_plan=session["plan"], feedback=prompt,
                )
                message = {"role": "assistant", "content": t("plan_updated")}
            else:
                intent = service.identify_intent(prompt)
                if intent == "reject":
                    message = {"role": "assistant", "content": t("readonly_notice")}
                elif intent == "analysis":
                    session["plan"] = service.analysis_plan(prompt, database)
                    session["question"] = prompt
                    message = {"role": "assistant", "content": t("plan_ready")}
                else:
                    result = service.query(prompt, database)
                    message = {
                        "role": "assistant",
                        "content": f"```sql\n{result['sql']}\n```",
                        "data": result["data"],
                        "schema_prompt": service.sql_prompt(prompt, database),
                    }
                    if result.get("warning"):
                        message["content"] += f"\n\n{result['warning']}"
            session["messages"].append(message)
        st.rerun()
except (ValueError, RuntimeError) as exc:
    message = {"role": "assistant", "content": f"{t('execution_failed')}: {exc}"}
    session["messages"].append(message)
    st.error(message["content"])

if st.button(t("clear_history")):
    session.clear()
    session.update(messages=[], plan=None, question=None)
    st.rerun()
