import streamlit as st

from utils import config_manager
from utils.i18n import t
from utils.resource_scope import ScopedConfig, resource_visibility


def reset_profile_drafts():
    keep = {"resource_profile", "language", "language_selector", "run_sessions", "open_run_id", "_profile_selector_rendered"}
    for key in list(st.session_state):
        if key not in keep:
            del st.session_state[key]
    st.session_state["chat_profile"] = st.session_state.get("resource_profile") or ""
    st.session_state["_config_profile"] = st.session_state.get("resource_profile")


def profile_changed():
    if st.session_state.get("_config_profile") != st.session_state.get("resource_profile"):
        reset_profile_drafts()


def profile_selector():
    profiles = config_manager.ConfigManager().load_profiles()
    if "_requested_profile" in st.session_state:
        st.session_state["resource_profile"] = st.session_state.pop("_requested_profile")
        reset_profile_drafts()
    if st.session_state.get("resource_profile") not in {None, *profiles}:
        st.session_state["resource_profile"] = None
        reset_profile_drafts()
    st.selectbox(t("resource_profile"), [None, *profiles], key="resource_profile",
                 format_func=lambda key: profiles[key]["name"] if key else t("shared_catalog"),
                 on_change=profile_changed)
    st.caption(t("profile_context_help"))
    st.session_state["_profile_selector_rendered"] = True


def ui_config():
    profile_id = st.session_state.get("resource_profile")
    if st.session_state.get("_config_profile", profile_id) != profile_id:
        reset_profile_drafts()
    st.session_state["_config_profile"] = profile_id
    return ScopedConfig(config_manager.ConfigManager(), profile_id)


def visibility_editor(item, key, profile_id, new=None):
    new = not bool(item) if new is None else new
    default = ("profile" if profile_id else "shared") if new else resource_visibility(item)
    options = ["shared", "profile"] if profile_id else ["shared"]
    selected = st.selectbox(t("resource_visibility"), options,
                            index=options.index(default) if default in options else 0,
                            format_func=lambda value: t(f"visibility_{value}"), key=f"{key}_visibility",
                            help=t("resource_visibility_help"))
    return {"visibility": selected, "profile_id": profile_id if selected == "profile" else None}


def writing_example(prefix, example, values=None):
    with st.expander(t("writing_example")):
        st.markdown(example)
        if values is not None and st.button(t("load_form_example"), key=f"{prefix}_example"):
            for key, value in values.items():
                st.session_state[key] = value


def delete_control(prefix, action):
    confirmed = st.checkbox(t("delete_config_confirmation"), key=f"{prefix}_delete_confirm")
    if st.button(t("delete"), disabled=not confirmed, key=f"{prefix}_delete_config"):
        try:
            action()
            st.session_state["semantics_saved"] = True
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
