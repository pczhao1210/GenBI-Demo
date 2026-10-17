from copy import deepcopy

from utils.tool_catalog import version_of


def snapshot_config(config):
    sources = config.load_datasources()
    return {"databases": config.load_database_config(), "schemas": config.load_schema_config(),
            "llm": config.load_llm_config(), "mcp": config.load_mcp_config(), "sources": sources,
            "semantics": config.load_semantics(), "knowledge": config.load_knowledge(),
            "model_roles": config.load_model_roles(), "methods": config.load_methods(),
            "tools": config.load_tools_config(), "tool_discovery": config.load_tool_discovery()}


class FrozenConfig:
    def __init__(self, snapshot):
        self.snapshot = deepcopy(snapshot)

    def load_database_config(self):
        return deepcopy(self.snapshot["databases"])

    def load_schema_config(self):
        return deepcopy(self.snapshot["schemas"])

    def load_llm_config(self):
        return deepcopy(self.snapshot["llm"])

    def load_mcp_config(self):
        return deepcopy(self.snapshot["mcp"])

    def load_datasources(self):
        return deepcopy(self.snapshot["sources"])

    def resolve_datasource(self, identifier):
        from utils.datasources import resolve_source
        return resolve_source(self.load_datasources(), identifier)

    def load_semantics(self):
        return deepcopy(self.snapshot["semantics"])

    def load_knowledge(self):
        return deepcopy(self.snapshot["knowledge"])

    def load_model_roles(self):
        return deepcopy(self.snapshot["model_roles"])

    def load_methods(self):
        return deepcopy(self.snapshot["methods"])

    def load_tools_config(self):
        from utils.tool_catalog import default_tools_config
        return deepcopy(self.snapshot.get("tools", default_tools_config()))

    def load_tool_discovery(self):
        return deepcopy(self.snapshot.get("tool_discovery", {}))


def source_fingerprint(source):
    return version_of({key: source.get(key) for key in (
        "datasource_id", "engine", "config", "schema", "timezone", "business_day_start")})


def step_compatible(step, old, new):
    from utils.tool_catalog import ToolCatalog
    kind = step["step_type"]
    if kind == "sql_query":
        identifier = step.get("datasource_id")
        if not identifier or identifier not in old["sources"] or identifier not in new["sources"]:
            return False
        if source_fingerprint(old["sources"][identifier]) != source_fingerprint(new["sources"][identifier]):
            return False
        if old["semantics"] != new["semantics"]:
            return False
    if kind in ("sql_query", "llm_analysis") and (
            old["llm"] != new["llm"] or old["model_roles"] != new["model_roles"]):
        return False
    if kind == "knowledge_retrieval" and old["knowledge"] != new["knowledge"]:
        return False
    tool_id = step.get("tool_id")
    if tool_id:
        before = ToolCatalog(FrozenConfig(old)).entries.get(tool_id)
        after = ToolCatalog(FrozenConfig(new)).entries.get(tool_id)
        if before is None or after is None or before["definition_version"] != after["definition_version"]:
            return False
    elif kind != "user_input" and version_of(old) != version_of(new):
        return False
    return True
