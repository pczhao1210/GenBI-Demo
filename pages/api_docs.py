import requests
import streamlit as st

from utils.i18n import t

st.set_page_config(page_title="API Documentation", page_icon="📚")
st.title(f"📚 {t('api_docs')}")
base_url = st.text_input("API Base URL", value="http://localhost:8000").rstrip("/")
st.subheader(t("service_status"))
try:
    response = requests.get(f"{base_url}/health", timeout=5)
    response.raise_for_status()
    st.success(t("api_service_normal"))
except requests.RequestException as exc:
    st.error(f"{t('offline')}: {exc}")

endpoints = {
    "/api/chat/generate-sql": {"question": "显示前10行数据", "database": "mysql"},
    "/api/chat/query": {"question": "显示前10行数据", "database": "mysql"},
    "/api/chat/analyze": {"question": "分析销售差异原因", "database": "mysql"},
    "/api/chat/execute-plan": {"question": "分析销售差异原因", "database": "mysql", "plan": {"steps": []}},
    "/api/chat/optimize-chain": {
        "original_chain": [], "feedback": "补充对比", "database": "mysql",
    },
    "/api/llm/chat": {"messages": [{"role": "user", "content": "Hello"}]},
    "/api/runs": {"question": "解释当前已定义的指标", "database": "mysql",
                  "submission_id": "replace-with-unique-client-id"},
}
st.subheader(t("api_endpoints"))
for endpoint in endpoints:
    st.code(f"POST {endpoint}", language="text")
st.markdown(f"[Swagger UI]({base_url}/docs) · [ReDoc]({base_url}/redoc)")

with st.expander(t("quick_test_api")):
    import json

    endpoint = st.selectbox(t("select_endpoint"), list(endpoints))
    body = st.text_area("JSON request", value=json.dumps(endpoints[endpoint], ensure_ascii=False, indent=2),
                        height=180, key=endpoint)
    if st.button(t("test_connection_btn")):
        try:
            payload = json.loads(body)
            response = requests.post(f"{base_url}{endpoint}", json=payload, timeout=300)
            if response.ok:
                st.json(response.json())
            else:
                st.error(f"HTTP {response.status_code}: {response.text}")
        except (requests.RequestException, ValueError) as exc:
            st.error(f"{t('connection_failed')}: {exc}")
