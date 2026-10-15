import json

import streamlit as st

from utils.config_manager import ConfigManager
from utils.i18n import t
from utils.semantics import KnowledgeIndex, parse_json

st.set_page_config(page_title="Semantics & knowledge", page_icon="📚", layout="wide")
st.title(t("semantics_title"))
config = ConfigManager()
ontology, knowledge = st.tabs([t("ontology_title"), t("knowledge_title")])
with ontology:
    st.caption(t("ontology_help"))
    value = st.text_area(t("ontology_json"), json.dumps(config.load_semantics() or {
        "version": 1, "entities": {}, "metrics": {}, "dimensions": {}, "relations": [],
    }, ensure_ascii=False, indent=2), height=350)
    if st.button(t("save_ontology")):
        try:
            config.save_semantics(parse_json(value))
            st.success(t("config_saved"))
        except ValueError as exc:
            st.error(str(exc))
with knowledge:
    docs = config.load_knowledge()
    index = KnowledgeIndex(docs)
    st.caption(f"{t('index_status')}: {len(index.chunks)}")
    title = st.text_input(t("document_title"))
    source = st.text_input(t("document_source"))
    version = st.text_input(t("document_version"), "1")
    scope = st.text_input(t("document_scope"), "*")
    text = st.text_area(t("document_text"))
    uploaded = st.file_uploader(t("import_document"), type=["txt", "md"])
    if st.button(t("add_document")):
        try:
            body = uploaded.getvalue().decode("utf-8") if uploaded else text
            from uuid import uuid4
            config.save_knowledge({"documents": [*docs.get("documents", []), {
                "id": uuid4().hex, "title": title, "source": source, "version": version,
                "scope": scope, "text": body,
            }]})
            st.success(t("config_saved"))
            st.rerun()
        except (ValueError, UnicodeError) as exc:
            st.error(str(exc))
    query = st.text_input(t("retrieval_test"))
    if query:
        for chunk in index.search(query):
            with st.expander(f"{chunk['title']} · {chunk['chunk_id']} · {chunk['score']:.2f}"):
                st.write(chunk["text"])
                st.json({key: value for key, value in chunk.items() if key != "text"})
