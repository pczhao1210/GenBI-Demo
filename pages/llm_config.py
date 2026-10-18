from copy import deepcopy

import streamlit as st

from utils.config_manager import ConfigManager
from utils.i18n import t
from utils.llm_client import LLMClient
from utils.model_config import available_models, connection_version, model_name, model_section, with_model
from utils.model_router import NODE_ROLES, effective_model
from utils.prompts import EXECUTION_CONTRACT, example_template
from utils.profile_ui import ui_config
from utils.resource_scope import resource_visibility, visible


def connection_editor(value):
    result = deepcopy(value)
    providers = ["openai", "azure_openai", "custom", "openai_sdk"]
    provider = st.selectbox(t("select_provider"), providers,
                            index=providers.index(value.get("provider", "openai")), key="global_provider")
    result["provider"] = provider
    section = model_section(result)
    connection = deepcopy(value.get(section, {}))
    connection["api_key"] = st.text_input("API Key", connection.get("api_key", ""),
                                         type="password", key=f"global_{section}_key")
    address = "endpoint" if section == "azure_openai" else "base_url"
    connection[address] = st.text_input(
        "Endpoint" if section == "azure_openai" else "Base URL",
        connection.get(address, "https://api.openai.com/v1" if section == "openai" else ""),
        key=f"global_{section}_{address}")
    with st.expander(t("model_connection_advanced")):
        for field in (["api_version"] if section == "azure_openai" else ["organization"] if section == "openai" else []):
            connection[field] = st.text_input(field, connection.get(field, ""), key=f"global_{section}_{field}")
        parameters = value.get("parameters", {})
        temperature = st.number_input("Temperature", 0.0, 2.0, float(parameters.get("temperature", 0.7)),
                                       key="global_temperature")
        max_tokens = st.number_input("Max Tokens", min_value=1, value=int(parameters.get("max_tokens", 4000)),
                                      key="global_tokens")
        result["parameters"] = {**parameters, "temperature": temperature, "max_tokens": max_tokens}
        timeout = value.get("timeout", {})
        mode = st.selectbox(t("timeout_mode"), ["auto", "global", "intent"],
                            index=0 if not timeout else 2 if isinstance(timeout, dict) else 1,
                            key="global_timeout_mode")
        if mode == "global":
            result["timeout"] = st.number_input(
                t("global_timeout_seconds"), min_value=1.0,
                value=float(timeout) if isinstance(timeout, (int, float)) else 70.0, key="global_timeout")
        elif mode == "intent":
            old = timeout if isinstance(timeout, dict) else {}
            result["timeout"] = {**old, **{
                kind: st.number_input(f"{t('timeout_config')} · {kind}", min_value=1.0,
                                      value=float(old.get(kind, default)), key=f"global_{kind}_timeout")
                for kind, default in (("query", 70), ("analysis", 240), ("default", 70))}}
        else:
            result["timeout"] = {}
        st.caption(t("model_advanced_preserved"))
    result[section] = connection
    return result


def model_picker(label, models, current, key, inherited=True, legacy=False):
    options = ["", *models]
    if current and current not in models:
        options.append(current)
    if legacy:
        options.append("__legacy__")
        current = "__legacy__"
    chosen = st.selectbox(label, options, index=options.index(current or ""), key=key,
                           format_func=lambda name: t("keep_legacy_model") if name == "__legacy__"
                           else name if name else t("inherit_model") if inherited else t("select_model"))
    if chosen and chosen not in models and chosen != "__legacy__":
        st.warning(t("saved_model_not_discovered"))
    return chosen


st.set_page_config(page_title="Models & prompts", page_icon="🤖", layout="wide")
st.title(t("llm_config"))
st.caption(t("model_catalog_flow"))
if st.session_state.pop("node_saved", False):
    st.success(t("config_saved"))
config = ui_config()
default_config = config.load_llm_config()
catalog = config.load_model_catalog()
global_tab, roles_tab, nodes_tab = st.tabs([t("global_default"), t("model_roles_title"), t("workflow_title")])
with global_tab:
    updated = connection_editor(default_config)
    if st.button(t("refresh_models"), type="primary", key="refresh_models"):
        try:
            section = model_section(updated)
            address = "endpoint" if section == "azure_openai" else "base_url"
            if not updated[section].get(address, "").strip():
                raise ValueError(t("model_connection_required"))
            with st.spinner(t("loading_models")):
                models = LLMClient(updated).list_models()
            config.save_model_catalog(updated, models)
            config.save_llm_config(updated)
            st.session_state["models_refreshed"] = True
            st.rerun()
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))
    if st.session_state.pop("models_refreshed", False):
        st.success(t("models_refreshed"))
    current_models = available_models(updated, catalog)
    if not current_models:
        st.info(t("refresh_models_hint"))
    else:
        st.caption(f"{len(current_models)} {t('available_models')} · {catalog.get('refreshed_at', '')}")
    default_model = model_picker(t("default_model"), current_models, model_name(updated),
                                  f"default_model_{connection_version(updated)}", inherited=False)
    if default_model:
        updated = with_model(updated, default_model)
    left, right = st.columns(2)
    test = left.button(t("test_connection"), key="test_global_model", disabled=not default_model)
    save = right.button(t("save_config"), key="save_global_model", disabled=not default_model)
    if test or save:
        try:
            if test:
                with st.spinner(t("testing_connection")):
                    response = LLMClient(updated).generate_response("Reply OK to test this connection.")
                st.success(t("connection_test_success"))
                st.write(response)
            else:
                config.save_llm_config(updated)
                st.success(t("config_saved"))
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))

default_config = config.load_llm_config()
models = available_models(default_config, config.load_model_catalog())
with roles_tab:
    st.caption(t("role_model_selection_help"))
    roles = config.load_model_roles()
    choices = {}
    for role in ("fast", "sql", "reasoning"):
        current = roles.get(role, {})
        choices[role] = model_picker(t(f"role_{role}"), models, current.get("model_name", ""),
                                     f"role_model_{role}_{connection_version(default_config)}",
                                     legacy=bool(current.get("provider")))
    if st.button(t("save_model_roles"), key="save_roles"):
        try:
            for role, selected in choices.items():
                if selected == "__legacy__":
                    continue
                if selected:
                    roles[role] = {"model_name": selected}
                else:
                    roles.pop(role, None)
            config.save_model_roles(roles)
            st.success(t("config_saved"))
        except ValueError as exc:
            st.error(str(exc))

with nodes_tab:
    with st.expander(t("effective_node_models")):
        rows = []
        for identifier, fallback in NODE_ROLES.items():
            selected_role, model, origin, _ = effective_model(config, fallback, identifier)
            rows.append({t("workflow_node"): t(f"node_{identifier}"), t("model_role"): selected_role,
                         t("model"): model_name(model) or t("needs_configuration"), t("config_origin"): t(origin)})
        st.dataframe(rows, hide_index=True, width="stretch")
        st.caption(t("code_only_states"))
    node = st.selectbox(t("workflow_node"), list(NODE_ROLES), format_func=lambda key: t(f"node_{key}"), key="prompt_node")
    st.caption(t(f"node_{node}_help"))
    workflow = config.load_workflow_config()
    current = workflow.get("nodes", {}).get(node, {})
    left, right = st.columns(2)
    with left:
        node_role = st.selectbox(t("model_role"), ["fast", "sql", "reasoning"],
                                 index=["fast", "sql", "reasoning"].index(current.get("role", NODE_ROLES[node])),
                                 key=f"node_role_{node}")
    with right:
        selected_model = model_picker(t("model"), models, current.get("model_name", ""),
                                       f"node_model_{node}_{connection_version(default_config)}",
                                       legacy="model" in current)
    default_prompt = config.load_prompt_defaults()[node]
    if st.button(t("restore_default_prompt"), key=f"restore_prompt_{node}"):
        st.session_state[f"node_prompt_{node}"] = default_prompt
    initial_prompt = current.get("prompt_template", default_prompt)
    if current.get("prompt"):
        initial_prompt += "\n" + current["prompt"]
    prompt = st.text_area(t("editable_node_prompt"), initial_prompt, height=300,
                          key=f"node_prompt_{node}", max_chars=20000, help=t("editable_prompt_help"))
    with st.expander(t("prompt_examples")):
        modes = ["zero_shot", "one_shot", "few_shot"]
        mode = st.selectbox(t("example_mode"), modes, index=modes.index(current.get("example_mode", "zero_shot")),
                            format_func=t, key=f"example_mode_{node}")
        scopes = ([config.profile_id] if config.profile_id else []) + ["__shared__"]
        if any(resource_visibility(item, example=True) == "legacy" for item in current.get("examples", [])):
            scopes.append(None)
        profile_id = st.selectbox(t("example_profile"), scopes,
                                  format_func=lambda key: t("visibility_shared") if key == "__shared__"
                                  else t("visibility_profile") if key else t("legacy_examples"),
                                  key=f"example_profile_{node}")
        st.caption(t("example_scope_help"))
        example_key = f"examples_{node}_{profile_id}"
        if st.session_state.pop(f"{example_key}_reset", False):
            st.session_state.pop(example_key, None)
        def in_example_group(item):
            scope = resource_visibility(item, example=True)
            return (scope == "shared" if profile_id == "__shared__" else
                    scope == "legacy" if profile_id is None else
                    scope == "profile" and item.get("profile_id") == profile_id)
        example_rows = [item for item in current.get("examples", []) if in_example_group(item)]
        if st.button(t("load_example_template"), key=f"load_{example_key}"):
            st.session_state[f"{example_key}_seed"] = [example_template(node)]
            st.session_state.pop(example_key, None)
        rows = st.session_state.get(f"{example_key}_seed",
                                    [{key: item[key] for key in ("input", "output")} for item in example_rows])
        examples = st.data_editor(rows or [{"input": "", "output": ""}], num_rows="dynamic", hide_index=True,
                                  key=example_key, column_config={
                                      "input": st.column_config.TextColumn(t("example_input"), width="large"),
                                      "output": st.column_config.TextColumn(t("example_output"), width="large")})
    with st.expander(t("prompt_execution_boundary")):
        st.code(EXECUTION_CONTRACT, language=None)
    if st.button(t("save_node"), type="primary", key=f"save_node_{node}"):
        try:
            scope = ({"visibility": "shared", "profile_id": None} if profile_id == "__shared__" else
                     {"profile_id": None} if profile_id is None else
                     {"visibility": "profile", "profile_id": profile_id})
            edited_examples = [{**item, **scope} for item in examples if item["input"] or item["output"]]
            all_examples = [item for item in current.get("examples", []) if not in_example_group(item)] + edited_examples
            minimum = {"zero_shot": 0, "one_shot": 1, "few_shot": 2}[mode]
            if len([item for item in all_examples if visible(item, config.profile_id, example=True)]) < minimum:
                raise ValueError(t("example_count_required"))
            updated_node = {**current, "role": node_role, "prompt_template": prompt,
                            "example_mode": mode, "examples": all_examples}
            updated_node.pop("prompt", None)
            if selected_model != "__legacy__":
                updated_node.pop("model", None)
                updated_node.pop("model_name", None)
                if selected_model:
                    updated_node["model_name"] = selected_model
            workflow.setdefault("nodes", {})[node] = updated_node
            config.save_workflow_config(workflow)
            st.session_state.pop(f"{example_key}_seed", None)
            st.session_state[f"{example_key}_reset"] = True
            st.session_state["node_saved"] = True
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
