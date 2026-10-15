from uuid import uuid4

import pandas as pd
import streamlit as st

from utils.config_manager import ConfigManager
from utils.i18n import t
from utils.run_service import TERMINAL, get_run_service
from utils.test_question_helper import get_test_question_input, render_test_question_sidebar

st.set_page_config(page_title="Smart Chat", page_icon="💬", layout="wide")
st.title(t("smart_chat"))
config = ConfigManager()
service = get_run_service()

with st.sidebar:
    database = st.selectbox(t("select_database"), ["mysql", "athena"])
    sessions = st.session_state.setdefault("run_sessions", {})
    session_id = sessions.setdefault(database, uuid4().hex)
    if st.button(t("new_conversation")):
        sessions[database] = uuid4().hex
        st.rerun()
    st.caption(t("readonly_notice"))
render_test_question_sidebar()


def show_result(run, step_id, step):
    st.caption(f"{step_id}: {step['status']}")
    if step.get("error"):
        st.error(step["error"])
    if not step.get("artifact_id"):
        return
    payload = service.store.artifact(run["run_id"], step["artifact_id"])
    data = payload.get("data")
    if isinstance(data, dict) and "columns" in data and "rows" in data:
        st.dataframe(pd.DataFrame(data["rows"], columns=data["columns"]))
        if data.get("truncated"):
            st.warning(t("result_truncated"))
    elif isinstance(data, str):
        st.markdown(data)
    elif data is not None:
        st.json(data)
    if payload.get("sql"):
        with st.expander("SQL"):
            st.code(payload["sql"], language="sql")


@st.fragment(run_every=1)
def workspace():
    for run in reversed(service.store.history(session_id)):
        run_id = run["run_id"]
        with st.chat_message("user"):
            st.markdown(run["question"])
        with st.chat_message("assistant"):
            st.write(f"{run['status']} · {run['phase']} · v{run['plan_version']}")
            completed = sum(s["status"] == "SUCCEEDED" for s in run["steps"].values())
            total = len((run.get("plan") or {}).get("steps", []))
            st.caption(f"{t('completed_steps')}: {completed}/{total}")
            if run.get("error"):
                st.error(run["error"])
            if run.get("plan"):
                with st.expander(t("analysis_plan")):
                    for step in run["plan"]["steps"]:
                        st.write(f"{step['step_id']}. {step.get('description', step['step_type'])}")
                    with st.expander(t("debug_details")):
                        st.json(run["plan"])
            for key, step in run["steps"].items():
                show_result(run, key, step)
            request = run.get("request")
            if run["status"] == "WAITING_INPUT" and request:
                st.info(request["prompt"])
                if request["request_kind"] == "plan_confirmation":
                    if st.button(t("execute_plan"), key=f"confirm_{run_id}"):
                        service.respond(run_id, request["request_id"], run["plan_version"], "confirm")
                        service.start(run_id)
                        st.rerun()
                else:
                    response = st.text_input(t("additional_input"), key=f"input_{run_id}")
                    if st.button(t("submit_response"), key=f"respond_{run_id}"):
                        service.respond(run_id, request["request_id"], run["plan_version"], response)
                        service.start(run_id)
                        st.rerun()
            if run["status"] not in TERMINAL:
                if st.button(t("cancel_plan"), key=f"cancel_{run_id}"):
                    service.cancel(run_id)
                    st.rerun()
                st.caption(t("cooperative_cancel"))
                if st.button(t("resume_run"), key=f"resume_{run_id}"):
                    service.recover(run_id)
                    service.start(run_id)
                    st.rerun()
            elif run["status"] in {"FAILED", "PARTIAL", "CANCELLED"}:
                if st.button(t("retry_plan"), key=f"retry_{run_id}"):
                    new = service.retry(run_id)
                    service.start(new["run_id"])
                    st.rerun()
            with st.expander(t("run_events")):
                st.json(service.store.events(run_id))


try:
    workspace()
    prompt = get_test_question_input() or st.chat_input(t("enter_question"))
    if prompt:
        run = service.submit(prompt, database, session_id, uuid4().hex)
        service.start(run["run_id"])
        st.rerun()
except (ValueError, RuntimeError) as exc:
    st.error(str(exc))

if st.button(t("clear_history")):
    sessions[database] = uuid4().hex
    st.rerun()
