"""Resource ownership for configuration discovery, separate from run allowlists."""

from copy import deepcopy
from functools import wraps

from filelock import FileLock


def resource_write(action):
    @wraps(action)
    def locked(config, *args, **kwargs):
        with FileLock(str(config.config_dir / "resources.lock"), is_singleton=True):
            return action(config, *args, **kwargs)
    return locked


def resource_visibility(item, example=False):
    if not isinstance(item, dict):
        raise ValueError("Resource visibility requires an object")
    if "visibility" in item:
        return item["visibility"]
    if example:
        return "profile" if item.get("profile_id") else "legacy"
    return "shared"


def visible(item, profile_id, example=False):
    scope = resource_visibility(item, example)
    return scope == "shared" or (
        scope == "profile" and profile_id is not None and item.get("profile_id") == profile_id
    ) or (scope == "legacy" and example and profile_id is None)


def validate_visibility(item, profiles=None, example=False):
    scope = resource_visibility(item, example)
    if scope not in (("shared", "profile", "legacy") if example else ("shared", "profile")):
        raise ValueError("Visibility must be shared or profile")
    if scope == "profile":
        owner = item.get("profile_id")
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("Profile-only resources require an owning Profile")
        if profiles is not None and owner not in profiles:
            raise ValueError(f"Unknown resource owner Profile: {owner}")
    elif item.get("profile_id") is not None:
        raise ValueError("Shared resources must not have an owning Profile")


def can_reference(owner, target):
    return resource_visibility(target) == "shared" or (
        resource_visibility(owner) == "profile" and target.get("profile_id") == owner.get("profile_id"))


def table_visible(source, table, profile_id):
    return visible(source, profile_id) and visible(source.get("schema", {}).get("table_scopes", {}).get(table, {}), profile_id)


def filter_source(source, profile_id):
    result = deepcopy(source)
    schema = result.setdefault("schema", {})
    tables = {table: info for table, info in schema.get("tables", {}).items()
              if table_visible(source, table, profile_id)}
    schema["tables"] = tables
    for field in ("descriptions", "table_scopes"):
        if field in schema:
            schema[field] = {key: value for key, value in schema[field].items() if key in tables}
    return result


def filter_ontology(ontology, sources, profile_id):
    result = deepcopy(ontology)
    for kind in ("entities", "metrics", "dimensions"):
        items = {}
        for identifier, item in result.get(kind, {}).items():
            if not visible(item, profile_id):
                continue
            original = item.get("mappings", {})
            mappings = {key: value for key, value in original.items()
                        if key in sources and value["table"] in sources[key]["schema"].get("tables", {})}
            if original and not mappings:
                continue
            if "mappings" in item:
                item["mappings"] = mappings
            items[identifier] = item
        if kind in result:
            result[kind] = items
    for metric in result.get("metrics", {}).values():
        if "allowed_dimensions" in metric:
            metric["allowed_dimensions"] = [key for key in metric["allowed_dimensions"]
                                             if key in result.get("dimensions", {})]
    for kind in ("metrics", "entities", "dimensions"):
        for item in result.get(kind, {}).values():
            for field, target in (("entity_ids", "entities"), ("dimension_ids", "dimensions")):
                if field in item:
                    item[field] = [key for key in item[field] if key in result.get(target, {})]
    if "relations" in result:
        result["relations"] = [relation for relation in result["relations"]
                               if relation["from"] in result.get("entities", {})
                               and relation["to"] in result.get("entities", {})]
    return result


def filter_workflow(workflow, profile_id):
    result = deepcopy(workflow)
    for settings in result.get("nodes", {}).values():
        if "examples" in settings:
            settings["examples"] = [item for item in settings["examples"] if visible(item, profile_id, example=True)]
    return result


def merge_records(before, after, available):
    hidden = set(before) - set(available)
    if hidden & set(after):
        raise ValueError("Cannot overwrite a resource outside the current Profile")
    return {**{key: deepcopy(before[key]) for key in hidden}, **deepcopy(after)}


def check_references(config, kind, before, after):
    """Block removal or narrowing of resources that a saved configuration uses."""
    for profile in config.load_profiles().values():
        keys = profile.get({"sources": "datasources", "knowledge": "knowledge_ids",
                            "methods": "method_ids", "queries": "query_ids"}.get(kind, ""), [])
        for identifier in keys:
            if identifier not in before:
                continue
            old, new = before[identifier], after.get(identifier)
            if visible(old, profile["id"]) and (new is None or not visible(new, profile["id"])):
                raise ValueError(f"Resource {identifier} is referenced by Profile {profile['name']}; unlink it first")
            if kind == "sources" and new:
                for table in profile["datasources"][identifier]:
                    if table in old.get("schema", {}).get("tables", {}) and (
                            table not in new.get("schema", {}).get("tables", {})
                            or not table_visible(new, table, profile["id"])):
                        raise ValueError(f"Table {table} is referenced by Profile {profile['name']}; unlink it first")
    if kind == "sources":
        for group in config.load_semantics().values():
            if not isinstance(group, dict):
                continue
            for identifier, item in group.items():
                for source_id, mapping in item.get("mappings", {}).items():
                    if source_id not in before:
                        continue
                    source = after.get(source_id)
                    table = mapping["table"]
                    if source is None or table not in source.get("schema", {}).get("tables", {}):
                        raise ValueError(f"Resource is referenced by business definition {identifier}; unlink it first")
                    info = source["schema"]["tables"][table]
                    columns = info.get("columns", []) if isinstance(info, dict) else info
                    if (not can_reference(item, source)
                            or not can_reference(item, source["schema"].get("table_scopes", {}).get(table, {}))
                            or set(mapping.get("columns", [])) - {column["name"] for column in columns}):
                        raise ValueError(f"Change conflicts with business definition {identifier}; update its mapping first")
    queries = config.load_query_knowledge().get("queries", [])
    for query in queries:
        bindings = query.get("bindings", {})
        refs = (bindings.get("semantics", {}).get(kind, []) if kind in ("metrics", "entities", "dimensions")
                else bindings.get(kind, []))
        for identifier in refs:
            if identifier not in before:
                continue
            target = after.get(identifier)
            if target is None or not can_reference(query, target):
                raise ValueError(f"Resource is referenced by query knowledge {query['question']}; unlink it first")
            if kind == "sources":
                for table in bindings["sources"][identifier]:
                    if (table not in target.get("schema", {}).get("tables", {})
                            or not can_reference(query, target["schema"].get("table_scopes", {}).get(table, {}))):
                        raise ValueError(f"Table is referenced by query knowledge {query['question']}; unlink it first")


class ScopedConfig:
    """Editable catalog view; saves merge invisible records instead of erasing them."""

    def __init__(self, config, profile_id=None):
        if profile_id is not None and profile_id not in config.load_profiles():
            raise ValueError(f"Unknown Profile: {profile_id}")
        self.base = config
        self.profile_id = profile_id

    def __getattr__(self, name):
        return getattr(self.base, name)

    def load_datasources(self):
        return {key: filter_source(source, self.profile_id) for key, source in self.base.load_datasources().items()
                if visible(source, self.profile_id)}

    def resolve_datasource(self, identifier):
        from utils.datasources import resolve_source
        return resolve_source(self.load_datasources(), identifier)

    def table_visible(self, source_id, table):
        source = self.base.resolve_datasource(source_id)
        return table_visible(source, table, self.profile_id)

    def load_schema_config(self):
        sources = self.load_datasources()
        result = {key: value["schema"] for key, value in sources.items()}
        for engine in {value["engine"] for value in sources.values()}:
            matches = [value for value in sources.values() if value["engine"] == engine]
            if len(matches) == 1:
                result[engine] = matches[0]["schema"]
        return result

    def load_database_config(self):
        sources = self.load_datasources()
        return {source["engine"]: source["config"] for source in sources.values()
                if sum(other["engine"] == source["engine"] for other in sources.values()) == 1}

    @resource_write
    def save_datasource(self, source):
        if not visible(source, self.profile_id):
            raise ValueError("Select the owning Profile before saving a private resource")
        previous = self.base.load_datasources().get(source["datasource_id"])
        if previous and not visible(previous, self.profile_id):
            raise ValueError("Datasource is outside the current Profile")
        source = deepcopy(source)
        if any(not visible(item, self.profile_id) for item in source.get("schema", {}).get("table_scopes", {}).values()):
            raise ValueError("Table schema is outside the current Profile")
        if previous:
            old = previous.get("schema", {})
            available = self.resolve_datasource(source["datasource_id"])["schema"]
            schema = source.setdefault("schema", {})
            for field in ("tables", "descriptions", "table_scopes"):
                schema[field] = merge_records(old.get(field, {}), schema.get(field, {}), available.get(field, {}))
        return filter_source(self.base.save_datasource(source), self.profile_id)

    @resource_write
    def save_schema_config(self, identifier, schema):
        source = self.resolve_datasource(identifier)
        return self.save_datasource({**source, "schema": schema})

    @resource_write
    def delete_datasource(self, identifier):
        source = self.resolve_datasource(identifier)
        if set(source["schema"].get("tables", {})) != set(
                self.base.resolve_datasource(identifier)["schema"].get("tables", {})):
            raise ValueError("Connection contains another Profile's table schemas; remove or share them first")
        self.base.delete_datasource(source["datasource_id"])

    def load_semantics(self):
        return filter_ontology(self.base.load_semantics(), self.load_datasources(), self.profile_id)

    @resource_write
    def save_semantics(self, value):
        from utils.semantics import validate_ontology
        validate_ontology(value, self.load_datasources())
        before, available = self.base.load_semantics(), self.load_semantics()
        sources = self.load_datasources()
        result = deepcopy(value)
        for kind in ("entities", "metrics", "dimensions"):
            for item in value.get(kind, {}).values():
                if not visible(item, self.profile_id):
                    raise ValueError("Business definition is outside the current Profile")
                for source_id, mapping in item.get("mappings", {}).items():
                    if source_id not in sources or mapping["table"] not in sources[source_id]["schema"].get("tables", {}):
                        raise ValueError("Business mapping is outside the current Profile")
                if set(item.get("allowed_dimensions", [])) - set(value.get("dimensions", {})):
                    raise ValueError("Dimension is outside the current editable definitions")
            result[kind] = merge_records(before.get(kind, {}), value.get(kind, {}), available.get(kind, {}))
            for key, item in result[kind].items():
                if key in available.get(kind, {}) and key in before.get(kind, {}):
                    old = before[kind][key]
                    if old.get("mappings"):
                        item["mappings"] = merge_records(old["mappings"], item.get("mappings", {}),
                                                         available[kind][key].get("mappings", {}))
                    hidden_dimensions = [dimension for dimension in old.get("allowed_dimensions", [])
                                         if dimension not in available.get("dimensions", {})]
                    if hidden_dimensions:
                        item["allowed_dimensions"] = hidden_dimensions + item.get("allowed_dimensions", [])
                    for field, target in (("entity_ids", "entities"), ("dimension_ids", "dimensions")):
                        hidden_refs = [ref for ref in old.get(field, []) if ref not in available.get(target, {})]
                        if hidden_refs:
                            item[field] = hidden_refs + item.get(field, [])
        if any(relation["from"] not in value.get("entities", {}) or relation["to"] not in value.get("entities", {})
               for relation in value.get("relations", [])):
            raise ValueError("Relation is outside the current editable definitions")
        hidden_relations = [r for r in before.get("relations", []) if r not in available.get("relations", [])]
        result["relations"] = hidden_relations + result.get("relations", [])
        self.base.save_semantics(result)

    def _load_library(self, loader, field):
        library = loader()
        result = {**library, field: [deepcopy(item) for item in library.get(field, []) if visible(item, self.profile_id)]}
        if field == "methods":
            for item in result[field]:
                if "cases" in item:
                    item["cases"] = [case for case in item["cases"] if visible(case, self.profile_id)]
        return result

    @resource_write
    def _save_library(self, value, field, loader, saver):
        if (not isinstance(value, dict) or not isinstance(value.get(field, []), list)
                or any(not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip()
                       for item in value.get(field, []))):
            raise ValueError(f"{field} requires a list of records with stable IDs")
        if field == "methods":
            from utils.analysis import validate_methods
            validate_methods(value, self.base.load_methods())
        before = loader()
        available = self._load_library(loader, field)
        for item in value.get(field, []):
            if not visible(item, self.profile_id):
                raise ValueError("Resource is outside the current Profile")
        if len({item["id"] for item in value.get(field, [])}) != len(value.get(field, [])):
            raise ValueError("Duplicate resource ID")
        merged = merge_records({i["id"]: i for i in before.get(field, [])},
                               {i["id"]: i for i in value.get(field, [])},
                               {i["id"]: i for i in available.get(field, [])})
        if field == "methods":
            for item in before.get(field, []):
                if item["id"] in {i["id"] for i in available.get(field, [])}:
                    hidden = [case for case in item.get("cases", []) if not visible(case, self.profile_id)]
                    if hidden:
                        if item["id"] not in merged:
                            raise ValueError("Method contains another Profile's cases; remove or share them first")
                        incoming = merged[item["id"]].get("cases", [])
                        if {case["id"] for case in hidden} & {case["id"] for case in incoming}:
                            raise ValueError("Case is outside the current Profile")
                        merged[item["id"]]["cases"] = hidden + merged[item["id"]].get("cases", [])
            for item in value.get(field, []):
                if any(not visible(case, self.profile_id) for case in item.get("cases", [])):
                    raise ValueError("Case is outside the current Profile")
        saver({**before, **value, field: list(merged.values())})

    def load_knowledge(self):
        return self._load_library(self.base.load_knowledge, "documents")

    def save_knowledge(self, value):
        self._save_library(value, "documents", self.base.load_knowledge, self.base.save_knowledge)

    def load_methods(self):
        return self._load_library(self.base.load_methods, "methods")

    def save_methods(self, value):
        self._save_library(value, "methods", self.base.load_methods, self.base.save_methods)

    def load_query_knowledge(self):
        return self._load_library(self.base.load_query_knowledge, "queries")

    def save_query_knowledge(self, value):
        self._save_library(value, "queries", self.base.load_query_knowledge, self.base.save_query_knowledge)

    def load_workflow_config(self):
        return filter_workflow(self.base.load_workflow_config(), self.profile_id)

    @resource_write
    def save_workflow_config(self, value):
        before = self.base.load_workflow_config()
        result = deepcopy(value)
        for key, settings in before.get("nodes", {}).items():
            hidden = [item for item in settings.get("examples", []) if not visible(item, self.profile_id, example=True)]
            if hidden:
                nodes = result.setdefault("nodes", {})
                if key not in nodes:
                    nodes[key] = {**deepcopy(settings), "examples": hidden}
                else:
                    nodes[key]["examples"] = hidden + nodes[key].get("examples", [])
        for settings in value.get("nodes", {}).values():
            if any(not visible(item, self.profile_id, example=True) for item in settings.get("examples", [])):
                raise ValueError("Example is outside the current Profile")
        self.base.save_workflow_config(result)
