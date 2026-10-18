import json
from copy import deepcopy
from uuid import uuid4

import streamlit as st

from utils.i18n import t
from utils.semantics import configuration_examples, parse_json
from utils.profile_ui import delete_control, ui_config, visibility_editor, writing_example
from utils.knowledge_center import (
    DEFAULT_STAGES, STAGES, catalog_entries, definition_name, entry_key, preview_knowledge, stages_for,
)


def select_record(items, prefix, title_key="title"):
    if f"{prefix}_saved" in st.session_state:
        st.session_state[f"{prefix}_record"] = st.session_state.pop(f"{prefix}_saved")
    if st.session_state.get(f"{prefix}_record", "__new__") not in {"__new__", *items}:
        st.session_state[f"{prefix}_record"] = "__new__"
    return st.selectbox(t("edit_or_add"), ["__new__", *items], key=f"{prefix}_record",
                        format_func=lambda key: t("add_new") if key == "__new__"
                        else f"{str(items[key].get(title_key, key))[:80]} · {key[-8:]}")


def saved_record(prefix, identifier):
    if prefix.startswith("case_"):
        st.session_state[f"{prefix}_saved"] = identifier
        st.session_state.pop(f"entry_json_{entry_key('methods', prefix[5:])}", None)
        key = entry_key("cases", identifier, prefix[5:])
    else:
        kind = {"knowledge": "documents", "method": "methods", "query_knowledge": "queries"}.get(prefix, prefix)
        key = entry_key(kind, identifier)
        st.session_state["_knowledge_saved_entry"] = key
    st.session_state.pop(f"entry_json_{key}", None)
    for label in ("ontology", "knowledge", "methods", "queries"):
        st.session_state.pop(f"advanced_{label}", None)
    st.session_state["semantics_saved"] = True
    st.rerun()


def open_entry(key):
    st.session_state["_knowledge_saved_entry"] = key
    st.rerun()


def stage_editor(item, kind, prefix):
    st.caption(t("kc_used_at") + " · ".join(t(f"kc_stage_{stage}") for stage in stages_for(item, kind)))
    with st.expander(t("kc_stage_settings")):
        st.caption(t("kc_stage_help"))
        stages = st.multiselect(t("kc_stage_choices"), list(DEFAULT_STAGES[kind]),
                                default=list(stages_for(item, kind)), format_func=lambda stage: t(f"kc_stage_{stage}"),
                                key=f"{prefix}_stages")
    return {"retrieval_stages": stages} if "retrieval_stages" in item or stages != list(DEFAULT_STAGES[kind]) else {}


def validation_fields(item, prefix):
    validation = item.get("validation", {})
    reviewer = st.text_input(t("reviewer"), validation.get("reviewer", ""), key=f"{prefix}_reviewer")
    fixtures = st.text_input(t("fixture_ids"), ", ".join(validation.get("fixture_ids", [])), key=f"{prefix}_fixtures")
    passed = st.checkbox(t("validation_passed"), validation.get("passed", False), key=f"{prefix}_passed")
    return {**validation, "reviewer": reviewer, "fixture_ids": [x.strip() for x in fixtures.split(",") if x.strip()],
            "passed": passed}


def ontology_editor(config, kind="metrics", selected="__new__"):
    st.caption(t(f"{kind}_guide"))
    ontology = config.load_semantics() or {"version": 1, "entities": {}, "metrics": {}, "dimensions": {}, "relations": []}
    items = ontology.get(kind, {})
    current = items.get(selected, {})
    prefix = f"{kind}_{selected}"
    example = {f"{prefix}_description": t(f"{kind}_example_definition"), f"{prefix}_name": t(f"kc_{kind}_name_example")}
    if kind == "metrics":
        example.update({f"{prefix}_subject": t("kc_subject_example"),
                        f"{prefix}_dimension_notes": t("kc_dimension_example")})
    writing_example(prefix, t(f"{kind}_writing_example"), example)
    name = st.text_input(t("kc_metric_name") if kind == "metrics" else t("kc_definition_name"),
                         definition_name(selected, current) if current else "", key=f"{prefix}_name")
    st.caption(t(f"kc_{kind}_name_example"))
    description = st.text_area(t("kc_metric_definition") if kind == "metrics" else t("business_definition"),
                               current.get("description", ""),
                               key=f"{prefix}_description", height=180, help=t("business_definition_help"))
    st.caption(t(f"{kind}_example_definition"))
    item = {**current, "description": description}
    if name.strip():
        item["name"] = name.strip()
    else:
        item.pop("name", None)
    if kind == "metrics":
        item["subject"] = st.text_area(t("kc_subject"), current.get("subject", ""), key=f"{prefix}_subject")
        st.caption(t("kc_subject_example"))
        item["dimension_notes"] = st.text_area(t("kc_dimension_notes"), current.get("dimension_notes", ""),
                                               key=f"{prefix}_dimension_notes")
        st.caption(t("kc_dimension_example"))
        st.caption(t("kc_dimension_advisory"))
    item.update(visibility_editor(current, prefix, config.profile_id))
    item.update(stage_editor(current, kind, prefix))
    with st.expander(t("semantic_optional")):
        identifier = st.text_input(t("tools_stable_id"), "" if selected == "__new__" else selected,
                                    disabled=selected != "__new__", key=f"{prefix}_id",
                                    help=t("semantic_id_help"))
        if kind == "metrics":
            left, right = st.columns(2)
            values = {
                "formula": left.text_input(t("metric_formula"), current.get("formula", ""), key=f"{prefix}_formula",
                                            help=t("metric_formula_help")),
                "aggregation": right.text_input(t("metric_aggregation"), current.get("aggregation", ""),
                                                key=f"{prefix}_aggregation"),
                "unit": left.text_input(t("metric_unit"), current.get("unit", ""), key=f"{prefix}_unit"),
                "time_field": right.text_input(t("metric_time"), current.get("time_field", ""), key=f"{prefix}_time"),
                "numerator": left.text_input(t("numerator"), current.get("numerator", ""), key=f"{prefix}_numerator"),
                "denominator": right.text_input(t("denominator"), current.get("denominator", ""), key=f"{prefix}_denominator"),
            }
            for field, value in values.items():
                if value.strip():
                    item[field] = value.strip()
                else:
                    item.pop(field, None)
            strict_dimensions = st.checkbox(t("kc_strict_dimensions"), value="allowed_dimensions" in current,
                                             key=f"{prefix}_strict_dimensions")
            dimensions = st.multiselect(t("metric_dimensions"), list(ontology.get("dimensions", {})),
                default=current.get("allowed_dimensions", []), key=f"{prefix}_dimensions")
            if strict_dimensions:
                item["allowed_dimensions"] = dimensions
            else:
                item.pop("allowed_dimensions", None)
            for field, target in (("entity_ids", "entities"), ("dimension_ids", "dimensions")):
                definitions = ontology.get(target, {})
                refs = st.multiselect(t(f"kc_link_{target}"), list(definitions), default=current.get(field, []),
                    format_func=lambda key, values=definitions: definition_name(key, values[key]),
                    key=f"{prefix}_{field}")
                if refs or field in current:
                    item[field] = refs
            old_filters = current.get("filters", "")
            displayed_filters = old_filters if isinstance(old_filters, str) else json.dumps(old_filters, ensure_ascii=False)
            filters = st.text_input(t("metric_filters"), displayed_filters, key=f"{prefix}_filters")
            if filters.strip():
                item["filters"] = old_filters if filters == displayed_filters else filters
            else:
                item.pop("filters", None)
        st.subheader(t("physical_mappings"))
        st.caption(t("physical_mappings_help"))
        sources = config.load_datasources()
        source_ids = st.multiselect(t("active_sources"), list(sources), default=list(current.get("mappings", {})),
                                    format_func=lambda key: sources[key]["name"], key=f"{prefix}_sources")
        mappings = {}
        for source_id in source_ids:
            old = current.get("mappings", {}).get(source_id, {})
            tables = sources[source_id]["schema"].get("tables", {})
            options = list(tables)
            table = st.selectbox(f"{sources[source_id]['name']} · {t('mapping_table')}", options,
                                  index=options.index(old["table"]) if old.get("table") in options else 0 if options else None,
                                  key=f"{prefix}_{source_id}_table")
            if table:
                info = tables[table]
                columns = [col["name"] for col in (info.get("columns", []) if isinstance(info, dict) else info)]
                selected_columns = st.multiselect(t("mapping_columns"), columns,
                    default=[col for col in old.get("columns", []) if col in columns],
                    key=f"{prefix}_{source_id}_{table}_columns")
                mappings[source_id] = {**old, "table": table, "columns": selected_columns}
            else:
                st.warning(t("profile_schema_required"))
        if mappings:
            item["mappings"] = mappings
        else:
            item.pop("mappings", None)
    if st.button(t("save_semantic"), type="primary", key=f"{prefix}_save"):
        try:
            if len(mappings) != len(source_ids):
                raise ValueError(t("profile_schema_required"))
            if not description.strip():
                raise ValueError(t("semantic_definition_required"))
            if kind == "metrics" and not name.strip():
                raise ValueError(t("kc_name_required"))
            identifier = identifier.strip() or f"{kind}_{uuid4().hex}"
            if selected == "__new__" and identifier in items:
                raise ValueError(t("semantic_id_exists"))
            updated = deepcopy(ontology)
            updated.setdefault(kind, {})[identifier] = {**item, "description": description.strip()}
            config.save_semantics(updated)
            saved_record(kind, identifier)
        except ValueError as exc:
            st.error(str(exc))
    if current and st.checkbox(t("confirm_delete"), key=f"{prefix}_delete_consent"):
        if st.button(t("delete"), key=f"{prefix}_delete"):
            try:
                del ontology[kind][selected]
                config.save_semantics(ontology)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def knowledge_editor(config, selected="__new__"):
    st.info(t("knowledge_guide"))
    knowledge = config.load_knowledge()
    docs = {doc["id"]: doc for doc in knowledge.get("documents", [])}
    doc = docs.get(selected, {})
    prefix = f"doc_{selected}"
    writing_example(prefix, t("knowledge_writing_example"), {
        f"{prefix}_title": t("knowledge_example_title"), f"{prefix}_text": t("knowledge_example_body")})
    scope = visibility_editor(doc, prefix, config.profile_id)
    title = st.text_input(t("document_title"), doc.get("title", ""), key=f"{prefix}_title")
    st.caption(t("knowledge_example_title"))
    text = st.text_area(t("document_text"), doc.get("text", ""), height=200, key=f"{prefix}_text")
    st.caption(t("knowledge_example_body"))
    uploaded = st.file_uploader(t("import_document"), type=["txt", "md"], key=f"{prefix}_upload")
    stage_settings = stage_editor(doc, "documents", prefix)
    with st.expander(t("knowledge_optional")):
        source = st.text_input(t("document_source"), doc.get("source", ""), key=f"{prefix}_source",
                               help=t("document_source_help"))
        version = st.text_input(t("document_version"), doc.get("version", "1"), key=f"{prefix}_version")
        collection = st.text_input(t("knowledge_collection"), doc.get("scope", "*"),
                              help=t("knowledge_collection_help"), key=f"{prefix}_scope")
    if st.button(t("save_document"), type="primary"):
        try:
            body = uploaded.getvalue().decode("utf-8") if uploaded else text
            identifier = doc.get("id") or uuid4().hex
            docs[identifier] = {**doc, **scope, **stage_settings, "id": identifier, "title": title,
                                "source": source.strip() or (uploaded.name if uploaded else f"manual:{identifier}"),
                                "version": version.strip() or "1", "scope": collection.strip() or "*", "text": body}
            config.save_knowledge({**knowledge, "documents": list(docs.values())})
            saved_record("knowledge", identifier)
        except (ValueError, UnicodeError) as exc:
            st.error(str(exc))
    if doc and st.checkbox(t("confirm_delete"), key=f"{prefix}_delete_consent"):
        if st.button(t("delete"), key=f"{prefix}_delete"):
            try:
                del docs[selected]
                config.save_knowledge({**knowledge, "documents": list(docs.values())})
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
def methods_editor(config, selected="__new__"):
    st.info(t("methods_guide"))
    library = config.load_methods()
    methods = {item["id"]: item for item in library.get("methods", [])}
    current = methods.get(selected, {})
    prefix = f"method_{selected}"
    writing_example(prefix, t("method_writing_example"), {
        f"{prefix}_title": t("method_example_title"), f"{prefix}_description": t("method_example_body")})
    scope = visibility_editor(current, prefix, config.profile_id)
    title = st.text_input(t("method_title"), current.get("title", ""), key=f"{prefix}_title")
    description = st.text_area(t("method_description"), current.get("description", ""), key=f"{prefix}_description")
    st.caption(t("method_example_body"))
    stage_settings = stage_editor(current, "methods", prefix)
    with st.expander(t("method_optional")):
        displayed_version = str(current.get("version", 1))
        version = st.text_input(t("document_version"), displayed_version, key=f"{prefix}_version")
        preconditions = deepcopy(current.get("preconditions", {}))
        for condition in ("has_time", "has_components"):
            value = st.checkbox(t(condition), preconditions.get(condition) is True, key=f"{prefix}_{condition}")
            if value:
                preconditions[condition] = True
            else:
                preconditions.pop(condition, None)
        from utils.tool_catalog import ToolCatalog
        capabilities = sorted({cap for tool in ToolCatalog(config).list() for cap in tool["capabilities"]}
                               | {"llm.analysis"} | set(current.get("required_capabilities", [])))
        required = st.multiselect(t("method_capabilities"), capabilities,
                                  default=current.get("required_capabilities", []), key=f"{prefix}_capabilities")
    old_steps = current.get("template", {}).get("steps", [])
    if st.session_state.pop(f"{prefix}_reset_steps", False):
        st.session_state.pop(f"{prefix}_steps", None)
    rows = [{"step_id": step["step_id"], "step_type": step["step_type"],
             "description": step.get("description", ""), "dependencies": ",".join(map(str, step.get("dependencies", [])))}
            for step in old_steps] or [{"step_id": 1, "step_type": "sql_query", "description": "", "dependencies": ""}]
    with st.expander(t("method_steps_optional")):
        st.caption(t("method_steps_help"))
        edited = st.data_editor(rows, num_rows="dynamic", hide_index=True, key=f"{prefix}_steps", column_config={
            "step_id": st.column_config.NumberColumn(t("step_number"), min_value=1, step=1, required=True),
            "step_type": st.column_config.SelectboxColumn(t("step_kind"), options=[
                "sql_query", "llm_analysis", "external_data", "knowledge_retrieval", "user_input", "compute", "data_align"],
                required=True),
            "description": st.column_config.TextColumn(t("step_description"), required=True),
            "dependencies": st.column_config.TextColumn(t("dependencies")),
        })
        st.caption(t("method_advanced_steps"))
    with st.expander(t("publication_optional")):
        transitions = {"draft": ["draft", "validated"], "validated": ["validated", "published", "draft"],
                       "published": ["published", "deprecated"], "deprecated": ["deprecated"]}
        status = st.selectbox(t("node_status"), transitions[current.get("status", "draft")],
                               format_func=t, key=f"{prefix}_status")
        validation = validation_fields(current, prefix)
    if st.button(t("save_method"), type="primary"):
        try:
            if not title.strip() or not description.strip():
                raise ValueError(t("method_required"))
            steps = []
            for row in edited:
                if (not str(row.get("description") or "").strip() and not row.get("dependencies")
                        and not any(step["step_id"] == row.get("step_id") for step in old_steps)):
                    continue
                if not row.get("step_id") or not str(row.get("description") or "").strip():
                    raise ValueError(t("method_step_required"))
                step_id = int(row["step_id"])
                if step_id != row["step_id"]:
                    raise ValueError(t("method_step_required"))
                old = next((step for step in old_steps if step["step_id"] == step_id), {})
                dependencies = [int(ref.strip()) for ref in (row["dependencies"] or "").split(",") if ref.strip()]
                step = {**old, **row, "step_id": step_id, "dependencies": dependencies}
                if step["step_type"] == "llm_analysis":
                    step["analysis_requirements"] = {**old.get("analysis_requirements", {}), "input_data": dependencies}
                steps.append(step)
            identifier = current.get("id") or uuid4().hex
            methods[identifier] = {**current, **scope, **stage_settings, "id": identifier, "title": title, "description": description,
                                   "version": current.get("version", 1) if version == displayed_version else version.strip() or "1",
                                   "preconditions": preconditions, "required_capabilities": required,
                                   "template": {**current.get("template", {}), "steps": steps},
                                   "status": status, "validation": validation}
            config.save_methods({**library, "methods": list(methods.values())})
            st.session_state[f"{prefix}_reset_steps"] = True
            saved_record("method", identifier)
        except (ValueError, TypeError) as exc:
            st.error(str(exc))
    if current:
        delete_control(prefix, lambda: config.save_methods({
            **library, "methods": [item for item in library["methods"] if item["id"] != selected]}))
        with st.expander(t("kc_method_cases")):
            cases_editor(config, selected)


def cases_editor(config, selected, chosen=None):
    st.info(t("cases_guide"))
    library = config.load_methods()
    methods = {item["id"]: item for item in library.get("methods", [])}
    method = methods[selected]
    st.caption(f"{t('case_method')}: {method['title']}")
    cases = {case["id"]: case for case in method.get("cases", [])}
    if chosen is None:
        chosen = select_record(cases, f"case_{selected}", "problem_structure")
    current = cases.get(chosen, {})
    prefix = f"case_{selected}_{chosen}"
    case = deepcopy(current)
    writing_example(prefix, t("case_writing_example"), {
        f"{prefix}_problem_structure": t("case_example_question"), f"{prefix}_adaptation": t("case_example_adaptation")})
    case.update(visibility_editor(current, prefix, config.profile_id))
    for field in ("problem_structure", "adaptation"):
        old = current.get(field, "")
        displayed = old if isinstance(old, str) else json.dumps(old, ensure_ascii=False)
        value = st.text_area(t(f"case_{field}"), displayed, key=f"{prefix}_{field}")
        case[field] = old if value == displayed else value
        st.caption(t("case_example_question" if field == "problem_structure" else "case_example_adaptation"))
    case.update(stage_editor(current, "cases", prefix))
    with st.expander(t("case_optional")):
        for field in ("required_data", "limitations"):
            old = current.get(field, "")
            displayed = old if isinstance(old, str) else json.dumps(old, ensure_ascii=False)
            value = st.text_area(t(f"case_{field}"), displayed, key=f"{prefix}_{field}")
            case[field] = old if value == displayed else value
    with st.expander(t("publication_optional")):
        case["status"] = st.selectbox(t("node_status"), ["draft", "validated", "published", "deprecated"],
                                      index=["draft", "validated", "published", "deprecated"].index(current.get("status", "draft")),
                                      format_func=t, key=f"{prefix}_status")
        case["validation"] = validation_fields(current, prefix)
    if st.button(t("save_case"), type="primary"):
        try:
            if not case["problem_structure"] or not case["adaptation"]:
                raise ValueError(t("case_required"))
            case["id"] = current.get("id") or uuid4().hex
            cases[case["id"]] = case
            method["cases"] = list(cases.values())
            config.save_methods({**library, "methods": list(methods.values())})
            saved_record(f"case_{selected}", case["id"])
        except ValueError as exc:
            st.error(str(exc))
    if current:
        def delete_case():
            method["cases"] = [item for item in method.get("cases", []) if item["id"] != chosen]
            config.save_methods({**library, "methods": list(methods.values())})
        delete_control(prefix, delete_case)


def query_knowledge_editor(config, selected="__new__"):
    st.info(t("query_knowledge_help"))
    library = config.load_query_knowledge()
    records = {item["id"]: item for item in library.get("queries", [])}
    current = records.get(selected, {})
    prefix = f"query_{selected}"
    writing_example(prefix, t("query_writing_example"), {
        f"{prefix}_question": t("query_example_question"), f"{prefix}_guidance": t("query_example_guidance")})
    scope = visibility_editor(current, prefix, config.profile_id)
    question = st.text_input(t("typical_question"), current.get("question", ""), key=f"{prefix}_question")
    st.caption(t("query_example_question"))
    guidance = st.text_area(t("query_guidance"), current.get("guidance", ""), key=f"{prefix}_guidance", height=180)
    st.caption(t("query_example_guidance"))
    stage_settings = stage_editor(current, "queries", prefix)
    with st.expander(t("kc_guide_examples")):
        st.caption(t("kc_guide_examples_help"))
        if st.session_state.pop(f"{prefix}_examples_reset", False):
            st.session_state.pop(f"{prefix}_examples", None)
        if st.button(t("load_form_example"), key=f"{prefix}_examples_seed"):
            st.session_state[f"{prefix}_examples_seed_rows"] = [{
                "question": t("case_example_question"), "guidance": t("case_example_adaptation")}]
            st.session_state.pop(f"{prefix}_examples", None)
        rows = st.session_state.get(f"{prefix}_examples_seed_rows", current.get("examples", []))
        edited_examples = st.data_editor(rows or [{"question": "", "guidance": ""}], num_rows="dynamic",
            hide_index=True, key=f"{prefix}_examples", column_config={
                "question": st.column_config.TextColumn(t("typical_question"), width="large"),
                "guidance": st.column_config.TextColumn(t("query_guidance"), width="large")})
    bindings = current.get("bindings", {})
    with st.expander(t("query_resource_links")):
        st.caption(t("query_links_help"))
        sources = config.load_datasources()
        chosen = st.multiselect(t("active_sources"), list(sources), default=list(bindings.get("sources", {})),
                                format_func=lambda key: sources[key]["name"], key=f"{prefix}_sources")
        source_links = {}
        for key in chosen:
            source_links[key] = st.multiselect(
                f"{sources[key]['name']} · {t('profile_tables')}", list(sources[key]["schema"].get("tables", {})),
                default=bindings.get("sources", {}).get(key, []), key=f"{prefix}_{key}_tables")
        semantics = config.load_semantics()
        semantic_links = {}
        for kind in ("metrics", "entities", "dimensions"):
            options = semantics.get(kind, {})
            semantic_links[kind] = st.multiselect(t(f"semantic_{kind}"), list(options),
                default=bindings.get("semantics", {}).get(kind, []),
                format_func=lambda key, items=options: definition_name(key, items[key]), key=f"{prefix}_{kind}")
        docs = {doc["id"]: doc for doc in config.load_knowledge().get("documents", [])}
        methods = {method["id"]: method for method in config.load_methods().get("methods", [])}
        knowledge = st.multiselect(t("profile_knowledge"), list(docs), default=bindings.get("knowledge", []),
                                   format_func=lambda key: docs[key]["title"], key=f"{prefix}_knowledge")
        selected_methods = st.multiselect(t("profile_methods"), list(methods), default=bindings.get("methods", []),
                                          format_func=lambda key: methods[key]["title"], key=f"{prefix}_methods")
    if st.button(t("save_query_knowledge"), type="primary", key=f"{prefix}_save"):
        try:
            identifier = current.get("id") or uuid4().hex
            examples = [{key: (row.get(key) or "").strip() for key in ("question", "guidance")}
                        for row in edited_examples if row.get("question") or row.get("guidance")]
            records[identifier] = {**current, **scope, **stage_settings, "id": identifier,
                                   "question": question, "guidance": guidance, "examples": examples,
                                   "bindings": {"sources": source_links, "semantics": semantic_links,
                                                "knowledge": knowledge, "methods": selected_methods}}
            config.save_query_knowledge({**library, "queries": list(records.values())})
            st.session_state.pop(f"{prefix}_examples_seed_rows", None)
            st.session_state[f"{prefix}_examples_reset"] = True
            saved_record("query_knowledge", identifier)
        except ValueError as exc:
            st.error(str(exc))
    if current:
        delete_control(prefix, lambda: config.save_query_knowledge({
            **library, "queries": [item for item in library["queries"] if item["id"] != selected]}))
        with st.expander(t("kc_linked_methods")):
            st.caption(t("kc_linked_methods_help"))
            for method_id in current.get("bindings", {}).get("methods", []):
                if st.button(methods[method_id]["title"], key=f"{prefix}_open_{method_id}"):
                    open_entry(entry_key("methods", method_id))


def entry_json_editor(config, entry):
    with st.expander(t("kc_entry_json")):
        st.caption(t("kc_stable_id_help"))
        st.download_button(t("kc_export_json"), json.dumps(entry["record"], ensure_ascii=False, indent=2),
                           file_name=f"knowledge-{entry['kind']}.json", mime="application/json",
                           key=f"entry_export_{entry['key']}")
        raw = st.text_area(t("kc_entry_json"), json.dumps(entry["record"], ensure_ascii=False, indent=2),
                           key=f"entry_json_{entry['key']}", height=220)
        if st.button(t("kc_save_json"), key=f"entry_json_save_{entry['key']}"):
            try:
                item = parse_json(raw)
                kind, identifier = entry["kind"], entry["id"]
                if kind in ("metrics", "entities", "dimensions"):
                    value = config.load_semantics()
                    value[kind][identifier] = item
                    config.save_semantics(value)
                else:
                    if item.get("id") != identifier:
                        raise ValueError(t("kc_stable_id_help"))
                    field, load, save = {
                        "documents": ("documents", config.load_knowledge, config.save_knowledge),
                        "queries": ("queries", config.load_query_knowledge, config.save_query_knowledge),
                        "methods": ("methods", config.load_methods, config.save_methods),
                        "cases": ("methods", config.load_methods, config.save_methods),
                    }[kind]
                    value = load()
                    if kind == "cases":
                        parent = next(method for method in value[field] if method["id"] == entry["parent"])
                        parent["cases"] = [item if case["id"] == identifier else case for case in parent["cases"]]
                    else:
                        value[field] = [item if old["id"] == identifier else old for old in value[field]]
                    save(value)
                prefix = (f"case_{entry['parent']}_{identifier}" if kind == "cases" else
                          f"{ {'documents': 'doc', 'queries': 'query', 'methods': 'method'}.get(kind, kind)}_{identifier}")
                for key in list(st.session_state):
                    if key.startswith(prefix + "_") or key == f"entry_json_{entry['key']}":
                        del st.session_state[key]
                open_entry(entry["key"])
            except ValueError as exc:
                st.error(str(exc))


st.set_page_config(page_title="Business knowledge center", page_icon="📚", layout="wide")
st.title(t("semantics_title"))
st.caption(t("kc_intro"))
if st.session_state.pop("semantics_saved", False):
    st.success(t("config_saved"))
config = ui_config()
entries = {entry["key"]: entry for entry in catalog_entries(config)}
if "_knowledge_saved_entry" in st.session_state:
    st.session_state["knowledge_entry"] = st.session_state.pop("_knowledge_saved_entry")
    for key in ("knowledge_search", "knowledge_type_filter", "knowledge_scope_filter"):
        st.session_state.pop(key, None)
catalog, detail = st.columns([1, 2.4], gap="large")
with catalog:
    if st.button(t("kc_add"), key="knowledge_add", use_container_width=True):
        open_entry("__new__")
    search = st.text_input(t("kc_search"), key="knowledge_search")
    family = st.selectbox(t("kc_type_filter"), ["all", "definitions", "guides", "references"],
                           format_func=lambda value: t(f"kc_{value}"), key="knowledge_type_filter")
    scope = st.selectbox(t("resource_visibility"), ["all", "shared", "profile"],
                          format_func=lambda value: t("kc_all") if value == "all" else t(f"visibility_{value}"),
                          key="knowledge_scope_filter")
    matches = {key: entry for key, entry in entries.items()
               if (family == "all" or entry["family"] == family)
               and (scope == "all" or entry["visibility"] == scope)
               and (not search or search.casefold() in json.dumps(entry["record"], ensure_ascii=False).casefold()
                    or search.casefold() in entry["title"].casefold())}
    if st.session_state.get("knowledge_entry") not in {"__new__", *matches}:
        st.session_state["knowledge_entry"] = "__new__"
    st.caption(t("kc_catalog_count").format(count=len(matches)))
    with st.container(height=380, border=False):
        selected = st.radio(t("kc_catalog"), ["__new__", *matches], key="knowledge_entry",
            format_func=lambda key: t("kc_add") if key == "__new__" else
            f"{matches[key]['title'][:60]} · {t('kc_kind_' + matches[key]['kind'])}")
    with st.expander(t("semantic_concepts")):
        st.markdown(t("semantic_concepts_help"))
with detail:
    entry = entries.get(selected)
    if entry:
        kind, identifier = entry["kind"], entry["id"]
        st.subheader(entry["title"])
        st.caption(f"{t('kc_kind_' + kind)} · {t('visibility_' + entry['visibility'])} · ID: {identifier}")
    else:
        template = st.radio(t("kc_new_template"), ["definitions", "guides", "references"],
                             format_func=lambda value: t(f"kc_{value}"), horizontal=True, key="knowledge_template")
        kind = {"definitions": "metrics", "guides": "queries", "references": "documents"}[template]
        if template != "references":
            with st.expander(t("kc_advanced_template")):
                choices = ["metrics", "entities", "dimensions"] if template == "definitions" else ["queries", "methods"]
                kind = st.selectbox(t("kc_advanced_template"), choices,
                                     format_func=lambda value: t(f"kc_kind_{value}"), key=f"knowledge_kind_{template}")
                st.caption(t("kc_advanced_template_help"))
        identifier = "__new__"
    if kind in ("metrics", "entities", "dimensions"):
        ontology_editor(config, kind, identifier)
    elif kind == "documents":
        knowledge_editor(config, identifier)
    elif kind == "queries":
        query_knowledge_editor(config, identifier)
    elif kind == "methods":
        methods_editor(config, identifier)
    else:
        if st.button(t("kc_open_parent"), key="open_case_method"):
            open_entry(entry_key("methods", entry["parent"]))
        cases_editor(config, entry["parent"], identifier)
    if entry:
        entry_json_editor(config, entry)

st.divider()
with st.expander(t("kc_retrieval_preview")):
    st.caption(t("kc_retrieval_help"))
    question = st.text_input(t("test_question"), key="knowledge_query", placeholder=t("query_example_question"))
    stage = st.selectbox(t("kc_stage_choices"), STAGES, format_func=lambda value: t(f"kc_stage_{value}"),
                         key="knowledge_preview_stage")
    if st.button(t("kc_run_preview"), key="knowledge_preview"):
        try:
            if not question.strip():
                raise ValueError(t("kc_preview_question_required"))
            preview = preview_knowledge(config, question, stage)
            for row in preview["used"]:
                st.write(f"**{row['title']}** · {t('kc_kind_' + row['kind'])} · {t('kc_reason_' + row['reason'])}")
            if not preview["used"]:
                st.info(t("retrieval_empty"))
            for row in preview["outside_run_scope"]:
                st.caption(f"{row['title']} · {t('kc_outside_scope')}" +
                           (f" · {t('kc_missing_links')}: {', '.join(row['missing'])}" if row["missing"] else ""))
            st.json(preview["context"], expanded=False)
        except ValueError as exc:
            st.error(str(exc))
with st.expander(t("kc_bulk_json")):
    st.caption(t("advanced_semantics_help"))
    examples = configuration_examples(config.load_datasources())
    for label, load, save in (
        ("ontology", config.load_semantics, config.save_semantics),
        ("knowledge", config.load_knowledge, config.save_knowledge),
        ("methods", config.load_methods, config.save_methods),
        ("queries", config.load_query_knowledge, config.save_query_knowledge),
    ):
        with st.expander(t(f"{label}_title") + " / JSON"):
            st.caption(t(f"example_{label}_help"))
            st.download_button(t("kc_export_json"), json.dumps(load(), ensure_ascii=False, indent=2),
                               file_name=f"knowledge-{label}.json", mime="application/json",
                               key=f"export_{label}")
            example = examples[label] if label != "queries" else {"queries": [{
                "id": "example-company-sales", "question": t("query_example_question"),
                "guidance": t("query_example_guidance")}]}
            st.code(json.dumps(example, ensure_ascii=False, indent=2), language="json")
            if st.button(t("load_json_example"), key=f"load_example_{label}"):
                st.session_state[f"advanced_{label}"] = json.dumps(example, ensure_ascii=False, indent=2)
            raw = st.text_area(t(f"{label}_json"), json.dumps(load(), ensure_ascii=False, indent=2),
                               height=300, key=f"advanced_{label}")
            if st.button(t(f"save_{label}"), key=f"advanced_save_{label}"):
                try:
                    save(parse_json(raw))
                    st.session_state["semantics_saved"] = True
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
