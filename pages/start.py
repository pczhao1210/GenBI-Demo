import streamlit as st

from utils.config_manager import ConfigManager
from utils.i18n import t
from utils.run_service import get_run_service

st.title(t("app_title"))
st.write(t("welcome_description"))
config = ConfigManager()
sources = config.load_datasources()
metrics = config.load_semantics().get("metrics", {})
steps = [
    (t("llm_config"), bool(config.load_llm_config()), "pages/llm_config.py"),
    (t("database_config"), any(source["config"] for source in sources.values()), "pages/database_config.py"),
    (t("schema_config"), any(source["schema"].get("tables") for source in sources.values()), "pages/schema_config.py"),
    (t("ontology_title"), any(metric.get("mappings") for metric in metrics.values()), "pages/semantics.py"),
]
st.subheader(t("setup_wizard"))
st.caption(t("configured_not_connected"))
for number, (label, ready, path) in enumerate(steps, 1):
    with st.container(border=True):
        left, right = st.columns([4, 1])
        left.write(f"{number}. {label} — {t('configured') if ready else t('needs_configuration')}")
        right.page_link(path, label=t("configure_now"))
left, right = st.columns(2)
left.page_link("pages/chat.py", label=t("start_analysis"), icon="💬")
right.page_link("pages/scenarios.py", label=t("try_sample_replay"), icon="🎬")
history = get_run_service().store.history()
if history:
    st.subheader(t("recent_runs"))
    for run in history[:5]:
        with st.container(border=True):
            st.write(f"{run['question']} · {run['status']} · {run['created_at']}")
            if st.button(t("open_run"), key=f"open_{run['run_id']}"):
                st.session_state["open_run_id"] = run["run_id"]
                st.switch_page("pages/chat.py")
