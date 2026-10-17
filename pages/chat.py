import json
from uuid import uuid4

import streamlit as st

from utils.config_manager import ConfigManager
from utils.i18n import t
from utils.run_service import TERMINAL, get_run_service
from utils.test_question_helper import get_test_question_input
from utils.result_view import render_citations, render_table
from utils.presentation import export_run
from utils.run_view import RunViewCache

st.set_page_config(page_title="Smart Chat", page_icon="💬", layout="wide")
st.title(t("smart_chat"))
config = ConfigManager()
service = get_run_service()
view_cache = st.session_state.setdefault("run_view_cache", RunViewCache())

with st.sidebar:
    sources = config.load_datasources()
    opened = st.session_state.pop("open_run_id", None)
    if opened:
        opened_run = service.store.get(opened)
        st.session_state.setdefault("run_sessions", {})[opened_run["database"]] = opened_run["session_id"]
        if opened_run["database"] in sources:
            st.session_state["primary_source"] = opened_run["database"]
    database = st.selectbox(t("select_database"), list(sources),
                            format_func=lambda key: f"{sources[key]['name']} ({sources[key]['engine']})",
                            key="primary_source")
    if not database:
        st.info(t("configure_source_hint"))
        database = "mysql"
    active_sources = st.multiselect(t("active_sources"), list(sources), default=[database] if database in sources else [],
                                    format_func=lambda key: sources[key]["name"])
    sessions = st.session_state.setdefault("run_sessions", {})
    session_id = sessions.setdefault(database, uuid4().hex)
    conversation_page = service.store.history_page(database=database, limit=20)
    history = list(conversation_page["items"])
    conversation_cursor = conversation_page["next_cursor"]
    for _ in range(st.session_state.get(f"conversation_depth_{database}", 0)):
        if conversation_cursor is None:
            break
        conversation_page = service.store.history_page(database=database, before=conversation_cursor, limit=20)
        history.extend(conversation_page["items"])
        conversation_cursor = conversation_page["next_cursor"]
    if conversation_cursor is not None and st.button(t("load_older_runs"), key=f"older_conversations_{database}"):
        st.session_state[f"conversation_depth_{database}"] = st.session_state.get(f"conversation_depth_{database}", 0) + 1
        st.rerun()
    conversations = {run["session_id"]: run["question"][:40] for run in reversed(history)
                     if run["database"] == database}
    choices = list(dict.fromkeys([session_id, *conversations]))
    session_id = st.selectbox(t("conversation_history"), choices,
                              format_func=lambda key: conversations.get(key, t("new_conversation")),
                              key=f"conversation_{database}_{sessions[database]}")
    if st.button(t("new_conversation")):
        sessions[database] = uuid4().hex
        st.rerun()
    st.caption(t("readonly_notice"))


def show_result(run, step_id, step):
    st.caption(f"{step_id}: {step['status']}")
    if step.get("error"):
        st.error(step["error"])
    if not step.get("artifact_id"):
        return
    payload = view_cache.artifact(service.store, session_id, run["run_id"], step["artifact_id"])
    data = payload.get("data")
    if isinstance(data, dict) and "columns" in data and "rows" in data:
        render_table(data, f"{run['run_id']}_{step_id}_{step['artifact_id']}", lazy_export=True)
    elif isinstance(data, str):
        st.markdown(data)
    elif data is not None and not any(key in data for key in ("sources", "chunks", "facts")):
        with st.expander(t("debug_details")):
            st.json(data)
    render_citations(payload, f"{run['run_id']}_{step_id}")
    if payload.get("sql"):
        with st.expander("SQL"):
            st.code(payload["sql"], language="sql")


polling = bool(service.store.history_page(
    session_id, limit=100, statuses=["QUEUED", "RUNNING", "CANCELLING"])["items"])


@st.fragment(run_every=1 if polling else None)
def workspace():
    page = service.store.history_page(session_id, limit=20)
    summaries = list(page["items"])
    cursor = page["next_cursor"]
    depth = st.session_state.get(f"history_depth_{session_id}", 0)
    for _ in range(depth):
        if cursor is None:
            break
        older = service.store.history_page(session_id, before=cursor, limit=20)
        summaries.extend(older["items"])
        cursor = older["next_cursor"]
    if cursor is not None and st.button(t("load_older_runs"), key=f"older_{session_id}"):
        st.session_state[f"history_depth_{session_id}"] = depth + 1
        st.rerun()
    active = service.store.history_page(session_id, limit=100, statuses=["QUEUED", "RUNNING", "CANCELLING"])["items"]
    seen = {item["run_id"] for item in summaries}
    summaries.extend(item for item in active if item["run_id"] not in seen)
    summaries.sort(key=lambda item: item["created_at"], reverse=True)
    latest = summaries[0]["run_id"] if summaries else None
    for summary in reversed(summaries):
        run_id = summary["run_id"]
        with st.chat_message("user"):
            st.markdown(summary["question"])
        with st.chat_message("assistant"):
            show = st.checkbox(t("show_run_details"), value=run_id == latest or summary["status"] in {
                "QUEUED", "RUNNING", "CANCELLING"},
                               key=f"details_{session_id}_{run_id}")
            if not show:
                st.caption(f"{summary['status']} · {summary['created_at']}")
                continue
            run = view_cache.snapshot(service.store, session_id, summary)
            st.write(f"{run['status']} · {run['phase']} · v{run['plan_version']}")
            if run.get("understanding"):
                with st.expander(t("understood_question")):
                    st.write(run["understanding"]["normalized_question"])
                    st.json(run["understanding"]["slots"])
            if run.get("answer_sufficiency"):
                st.caption(f"{t('answer_sufficiency')}: {run['answer_sufficiency']}")
            if run.get("report"):
                st.markdown(run["report"])
            if run.get("ledger"):
                with st.expander(t("analysis_ledger")):
                    st.json(run["ledger"])
            completed = sum(s["status"] == "SUCCEEDED" for s in run["steps"].values())
            total = len((run.get("plan") or {}).get("steps", []))
            st.caption(f"{t('completed_steps')}: {completed}/{total}")
            if run.get("error"):
                st.error(run["error"])
            if run.get("plan"):
                with st.expander(t("analysis_plan")):
                    for step in run["plan"]["steps"]:
                        with st.container(border=True):
                            st.write(f"{step['step_id']}. {step.get('description', step['step_type'])}")
                            st.caption(f"{step['step_type']} · {step.get('datasource_id', '')} · "
                                       f"{t('dependencies')}: {step['dependencies']}")
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
                    feedback = st.text_input(t("plan_feedback"), key=f"feedback_{run_id}")
                    if st.button(t("revise_plan"), key=f"refine_{run_id}"):
                        service.refine(run_id, request["request_id"], run["plan_version"], feedback)
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
            if run["status"] in TERMINAL:
                st.caption(f"{t('historical_result')} · {run['created_at']}")
                if st.button(t("refresh_analysis"), key=f"refresh_{run_id}"):
                    new = service.retry(run_id, refresh=True)
                    service.start(new["run_id"])
                    st.rerun()
                if st.button(t("prepare_export"), key=f"prepare_export_{run_id}"):
                    replay = service.store.replay(run_id)
                    st.session_state["prepared_export"] = (session_id, run_id, run["updated_at"], export_run(replay))
                prepared = st.session_state.get("prepared_export")
                if prepared and prepared[:3] == (session_id, run_id, run["updated_at"]):
                    exported, media, extension = prepared[3]
                    st.download_button(t("download_run"), exported, file_name=f"{run_id}.{extension}",
                                       mime=media, key=f"export_{run_id}")
            if st.checkbox(t("show_run_events"), key=f"events_{session_id}_{run_id}"):
                with st.expander(t("run_events"), expanded=True):
                    st.json(view_cache.read_events(service.store, session_id, run_id))
    currently_active = bool(active)
    if polling != currently_active:
        st.rerun()


try:
    workspace()
    prompt = get_test_question_input() or st.chat_input(t("enter_question"))
    if prompt:
        run = service.submit(prompt, database, session_id, uuid4().hex, datasource_ids=active_sources)
        service.start(run["run_id"])
        st.rerun()
except (ValueError, RuntimeError) as exc:
    st.error(str(exc))

if st.button(t("clear_history")):
    sessions[database] = uuid4().hex
    st.rerun()
