import pandas as pd
import plotly.express as px
import streamlit as st

from utils.i18n import t
from utils.presentation import chart_spec, csv_export, numeric


def render_table(data, key):
    if data.get("truncated") or data.get("completeness") not in (None, "COMPLETE"):
        st.warning(t("result_truncated"))
    for warning in data.get("warnings", []):
        st.warning(str(warning))
    if data.get("row_count") == 0 or not data["rows"]:
        st.info(t("empty_result"))
    if len(data["rows"]) == 1:
        values = [(name, value) for name, value in zip(data["columns"], data["rows"][0]) if numeric(value)][:4]
        if values:
            cards = st.columns(len(values))
            for card, (name, value) in zip(cards, values):
                card.metric(name, f"{value} {data.get('units', {}).get(name, '')}".strip())
    spec = chart_spec(data)
    mode = st.radio(t("result_view"), [t("table_view"), t("chart_view")], horizontal=True,
                    key=f"view_{key}") if spec else t("table_view")
    df = pd.DataFrame(data["rows"], columns=data["columns"])
    if mode == t("chart_view"):
        df[spec["y"]] = pd.to_numeric(df[spec["y"]], errors="raise")
        if spec["kind"] == "line":
            df = df.sort_values(spec["x"])
            figure = px.line(df, x=spec["x"], y=spec["y"], markers=True)
        elif spec["kind"] == "pie":
            figure = px.pie(df, names=spec["x"], values=spec["y"])
        else:
            figure = px.bar(df, x=spec["x"], y=spec["y"])
        figure.update_layout(yaxis_title=f"{spec['y']} ({spec['unit']})" if spec["unit"] else spec["y"])
        st.plotly_chart(figure, key=f"chart_{key}", width="stretch")
        st.caption(t("chart_precision"))
    else:
        st.dataframe(df, width="stretch")
    with st.expander(t("result_scope")):
        st.json({name: value for name, value in data.items() if name not in ("rows", "columns")})
    st.download_button(t("download_csv"), csv_export(data).encode("utf-8-sig"),
                       file_name=f"{key}.csv", mime="text/csv", key=f"csv_{key}")


def render_citations(payload, key):
    citations = payload.get("citations", [])
    data = payload.get("data")
    if isinstance(data, dict):
        citations = [*citations, *data.get("sources", []), *data.get("chunks", [])]
        for warning in data.get("warnings", []):
            st.warning(str(warning))
        if data.get("facts"):
            st.dataframe(pd.DataFrame(data["facts"]), width="stretch")
    if citations:
        with st.expander(t("evidence_sources")):
            for index, citation in enumerate(citations):
                st.write(citation.get("title", citation.get("chunk_id", citation.get("url", ""))))
                source = citation.get("url", citation.get("source", ""))
                if source.startswith(("http://", "https://")):
                    st.link_button(t("open_source"), source)
                st.json({name: value for name, value in citation.items() if name not in ("text", "content")})
                if citation.get("text"):
                    st.text(citation["text"])
