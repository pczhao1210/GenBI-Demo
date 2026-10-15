import json

import streamlit as st

from utils.computation import compute
from utils.config_manager import ConfigManager, PROJECT_ROOT
from utils.i18n import get_language, t
from utils.result_view import render_table
from utils.semantics import KnowledgeIndex

st.title(t("demo_scenarios"))
config = ConfigManager()
library = json.loads((PROJECT_ROOT / "config/example_scenarios.json").read_text(encoding="utf-8"))
lang = get_language()
sources = config.load_datasources()
readiness = {
    "llm": bool(config.load_llm_config()),
    "knowledge": bool(KnowledgeIndex(config.load_knowledge()).chunks),
    "datasource": bool(sources), "multiple_sources": len(sources) >= 2,
    "schema": any(source["schema"].get("tables") for source in sources.values()),
    "semantics": bool(config.load_semantics().get("metrics")),
}
for scenario in library["scenarios"]:
    with st.container(border=True):
        st.subheader(scenario["title"][lang])
        st.write(scenario["description"][lang])
        missing = [item for item in scenario["prerequisites"] if not readiness[item]]
        st.caption(f"{t('prerequisites')}: {', '.join(scenario['prerequisites'])}")
        if missing:
            st.info(f"{t('missing_prerequisites')}: {', '.join(missing)}")
        st.write(scenario["question"][lang])
        for followup in scenario["followups"][lang]:
            st.caption(f"↳ {followup}")
        if st.button(t("use_scenario"), key=scenario["id"], disabled=bool(missing)):
            st.session_state["selected_test_question"] = scenario["question"][lang]
            st.switch_page("pages/chat.py")
st.subheader(t("sample_replay"))
sample = library["sample"]
st.warning(f"SAMPLE_REPLAY · {sample['captured_at']} · {sample['description'][lang]}")
render_table(sample["data"], "sample")
ratio = compute({"operation": "ratio", "inputs": [1], "numerator": "numerator",
                 "denominator": "denominator", "output": "ratio"}, {1: {"data": sample["data"]}})
render_table(ratio["data"], "sample_ratio")
