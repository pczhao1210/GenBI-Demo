import streamlit as st

from utils.i18n import language_selector, t

st.set_page_config(page_title="GenBI", page_icon="🔍", layout="wide")
with st.sidebar:
    language_selector()
navigation = st.navigation({
    t("workspace_nav"): [
        st.Page("pages/start.py", title=t("start_page"), icon="🏠", default=True),
        st.Page("pages/chat.py", title=t("smart_chat"), icon="💬"),
        st.Page("pages/scenarios.py", title=t("demo_scenarios"), icon="🎬"),
    ],
    t("configuration_nav"): [
        st.Page("pages/database_config.py", title=t("database_config"), icon="🗄️"),
        st.Page("pages/schema_config.py", title=t("schema_config"), icon="📋"),
        st.Page("pages/semantics.py", title=t("semantics_title"), icon="📚"),
        st.Page("pages/llm_config.py", title=t("llm_config"), icon="🤖"),
        st.Page("pages/tools.py", title=t("tools_title"), icon="🛠️"),
    ],
    t("developer_nav"): [st.Page("pages/api_docs.py", title=t("api_docs"), icon="🔧")],
})
navigation.run()
