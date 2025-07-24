import streamlit as st
from utils.i18n import t, language_selector

st.set_page_config(
    page_title="GenBI - Generative BI Query System",
    page_icon="🔍",
    layout="wide"
)

# 设置当前页面为主页
st.session_state.current_page = 'main'

st.title(f"🔍 {t('app_title')}")
st.markdown(t('app_subtitle'))

# 侧边栏导航
st.sidebar.title(t('navigation'))

# 语言选择器 (仅在主页显示)
with st.sidebar:
    language_selector()
    st.divider()

pages = {
    t('llm_config'): "pages/llm_config.py",
    t('database_config'): "pages/database_config.py", 
    t('schema_config'): "pages/schema_config.py",
    t('smart_chat'): "pages/chat.py",
    t('mcp_management'): "pages/mcp_management.py",
    t('api_docs'): "pages/api_docs.py"
}

# 主页内容
st.markdown(f"""
## {t('features')}

{t('feature_smart_query')}
{t('feature_data_analysis')}
{t('feature_multi_source')}
{t('feature_mcp')}
{t('feature_api')}

## {t('quick_start')}
{t('quick_start_content')}
""")