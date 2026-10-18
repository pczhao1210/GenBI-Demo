"""Runtime tool definitions shared by planning, execution and management."""

import hashlib
import json
import shutil
from copy import deepcopy
from functools import lru_cache

CATEGORIES = {
    "database": "Database", "knowledge": "Knowledge", "compute": "Computation",
    "search": "Search", "fetch": "Fetch", "external_api": "External API",
    "reasoning": "Planning assistance",
}


def version_of(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def matches_definition_version(definition, version):
    if version == definition["definition_version"]:
        return True
    previous = {key: value for key, value in definition.items() if key != "definition_version"}
    variants = [previous]
    if definition["tool_id"].startswith("local:compute."):
        previous = deepcopy(previous)
        previous["input_schema"]["properties"].pop("output", None)
        variants.append(previous)
    # Accept the prior timestamp-inclusive hash and the additive output-schema change
    # only when every other frozen definition/configuration field still matches.
    return any(version == version_of(item) or version == version_of({
        key: value for key, value in item.items() if key != "discovered_at"})
        for item in variants)


def server_version(settings):
    connection = ("protocol", "type", "command", "args", "cwd", "env_refs", "header_refs", "url", "timeout", "tools")
    return version_of({key: settings[key] for key in connection if key in settings})


def object_schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False}


def local_definitions():
    text = {"type": "string", "minLength": 1}
    strings = {"type": "array", "items": text}
    refs = {"type": "array", "items": {"type": "integer", "minimum": 1},
            "minItems": 1, "uniqueItems": True}
    definitions = []
    for capability, category, description, schema, output in (
        ("database.query", "database", "Execute one read-only SQL query on an explicit datasource.",
         object_schema({"datasource_id": text, "sql": text}, ("datasource_id", "sql")), "table"),
        ("database.metadata", "database", "Read tables or columns from an explicit datasource.",
         object_schema({"datasource_id": text, "table": text}, ("datasource_id",)), "metadata"),
        ("database.preview", "database", "Read a sampled preview, never a complete dataset.",
         object_schema({"datasource_id": text, "table": text,
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                       ("datasource_id", "table")), "sample"),
        ("knowledge.search", "knowledge", "Search internal sources; an empty result means no matching knowledge.",
         object_schema({"query": text, "scope": text,
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, ("query",)), "knowledge"),
        ("external.fetch", "fetch", "Fetch a known public URL with bounded redirects and response size.",
         object_schema({"url": text}, ("url",)), "document"),
    ):
        definitions.append(_definition(capability, category, description, schema, output))
    common = {"inputs": refs, "group_by": strings, "output": text,
              "null_policy": {"enum": ["reject", "exclude"]}}
    for operation, fields, required, description in (
        ("join", {"left_on": strings, "right_on": strings,
                  "how": {"enum": ["inner", "left", "outer"]},
                  "cardinality": {"enum": ["one_to_one", "one_to_many", "many_to_one"]},
                  "max_unmatched_ratio": {"type": "number", "minimum": 0, "maximum": 1}},
         ("left_on", "right_on", "cardinality"),
         "Join two complete, compatible tables. Reject many-to-many and diagnose duplicated measures."),
        ("aggregate", {"columns": strings}, ("columns",),
         "Group and SUM declared numeric columns, not arbitrary aggregation. Reject repeated measures."),
        ("ratio", {"numerator": text, "denominator": text}, ("numerator", "denominator"),
         "Sum numerator and denominator separately before dividing; zero denominator produces NULL."),
        ("difference", {"numerator": text, "denominator": text}, ("numerator", "denominator"),
         "Subtract separately summed operands with explicitly matching units."),
    ):
        parameters = ({"inputs": {**refs, "minItems": 2, "maxItems": 2}} if operation == "join" else
                      {**common, "inputs": {**refs, "maxItems": 1}})
        definitions.append(_definition(
            f"compute.{operation}", "compute", description,
            object_schema({**parameters, **fields}, ("inputs", *required)), "calculation"))
    return definitions


def _definition(capability, category, description, schema, output):
    return {"tool_id": f"local:{capability}", "backend": "local", "tool_name": capability,
            "categories": [category], "capabilities": [capability], "description": description,
            "when_to_use": description, "input_schema": schema, "output_kind": output,
            "enabled": True, "policy": {"read_only": True, "idempotent": True,
                                       "timeout": 300 if category == "database" else 30,
                                       "concurrency": 4, "session_scope": "call"}}


def default_tools_config():
    return {"schema_version": 1, "categories": dict(CATEGORIES), "tools": {},
            "default_providers": {}}


def validate_tools_config(config):
    if (not isinstance(config, dict) or type(config.get("schema_version")) is not int
            or config["schema_version"] != 1):
        raise ValueError("Unsupported tools configuration schema_version")
    categories = config.get("categories")
    if (not isinstance(categories, dict) or any(
            not isinstance(key, str) or not key or not isinstance(name, str) or not name.strip()
            for key, name in categories.items())):
        raise ValueError("Categories require stable IDs and non-empty display names")
    if not isinstance(config.get("tools"), dict) or not isinstance(config.get("default_providers"), dict):
        raise ValueError("Tools and default_providers must be objects")
    for tool_id, override in config["tools"].items():
        if not isinstance(tool_id, str) or not isinstance(override, dict):
            raise ValueError("Tool overrides must be keyed by stable tool ID")
        if set(override) - {"enabled", "categories", "description", "when_to_use", "policy"}:
            raise ValueError(f"Unsupported tool override: {tool_id}")
        if "enabled" in override and type(override["enabled"]) is not bool:
            raise ValueError("Tool enabled must be boolean")
        if "categories" in override and (not isinstance(override["categories"], list)
                or any(category not in categories for category in override["categories"])):
            raise ValueError(f"Unknown tool category: {tool_id}")
        for field in ("description", "when_to_use"):
            if field in override and (not isinstance(override[field], str) or not override[field].strip()):
                raise ValueError(f"{field} must be non-empty text")
        policy = override.get("policy", {})
        if not isinstance(policy, dict) or set(policy) - {
                "timeout", "concurrency", "read_only", "idempotent", "session_scope"}:
            raise ValueError("Unsupported tool policy")
        for field in ("timeout", "concurrency"):
            if field in policy and (type(policy[field]) is not int or not 1 <= policy[field] <= 300):
                raise ValueError(f"Tool {field} must be an integer from 1 to 300")
        for field in ("read_only", "idempotent"):
            if field in policy and type(policy[field]) is not bool:
                raise ValueError(f"Tool {field} must be boolean")
        if policy.get("session_scope", "call") not in ("call", "run"):
            raise ValueError("Tool session_scope must be call or run")
    if any(not isinstance(k, str) or not isinstance(v, str)
           for k, v in config["default_providers"].items()):
        raise ValueError("Default providers must map capability to tool_id")
    return config


class ToolCatalog:
    def __init__(self, config):
        self.config = config
        self.settings = config.load_tools_config()
        self.servers = config.load_mcp_config()
        snapshot = json.dumps({"settings": self.settings, "servers": self.servers,
                               "has_sources": bool(config.load_datasources()),
                               "discoveries": config.load_tool_discovery().get("servers", {})},
                              sort_keys=True, ensure_ascii=False)
        build = _cached_entries if len(snapshot.encode()) <= 1024 * 1024 else _build_entries
        self.entries = deepcopy(build(snapshot))
        self.version = version_of({"definitions": list(self.entries.values()), "configuration": self.settings})

    def _populate(self, has_sources, discoveries):
        self.entries = {}
        for definition in local_definitions():
            reason = None
            if definition["categories"] == ["database"] and not has_sources:
                reason = "No datasource configured"
            self._add(definition, reason)
        search = self.servers.get("playwright")
        if search and search.get("protocol") != "mcp":
            self._add({
                **_definition("external.search", "search", "Discover sources; snippets are not observations.",
                              object_schema({"query": {"type": "string", "minLength": 1},
                                             "max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
                                            ("query",)), "discovery"),
                "tool_id": "legacy:playwright:search_web", "backend": "legacy_rpc",
                "server_id": "playwright", "tool_name": "search_web",
            }, None if search.get("status") == "active" else "Server disabled",
                version_of(search))
            self._add({
                **_definition("external.fetch", "fetch", "Legacy browser retrieval; completeness is unknown.",
                              object_schema({"url": {"type": "string", "minLength": 1}}, ("url",)), "document"),
                "tool_id": "legacy:playwright:fetch_page", "backend": "legacy_rpc",
                "server_id": "playwright", "tool_name": "fetch_page", "compatibility_only": True,
            }, None if search.get("status") == "active" else "Server disabled", version_of(search))
        for server_id, server in self.servers.items():
            if server.get("protocol") != "mcp":
                continue
            snapshot = discoveries.get(server_id, {})
            matching = snapshot.get("config_version") == server_version(server)
            tools = snapshot.get("tools", []) if matching else []
            for tool in tools:
                name = tool["name"]
                mappings = server.get("capabilities", {})
                if not isinstance(mappings, dict):
                    raise ValueError(f"Standard MCP capabilities must be a mapping: {server_id}")
                capabilities = [key for key, value in mappings.items() if value == name]
                if not capabilities:
                    capabilities = [f"mcp.{server_id}.{name}"]
                categories = server.get("categories", [])
                annotations = tool.get("annotations") or {}
                read_only = annotations.get("readOnlyHint", server.get("template") == "fetch"
                                             or not server.get("tool_confirmation_required", False))
                reasoning = ("reasoning.sequential_thinking" in capabilities
                             or server.get("template") == "sequential_thinking")
                definition = {
                    "tool_id": f"mcp:{server_id}:{name}", "backend": "mcp", "server_id": server_id,
                    "tool_name": name, "categories": categories, "capabilities": capabilities,
                    "description": tool.get("description", name),
                    "when_to_use": server.get("when_to_use") or tool.get("description", ""),
                    "input_schema": tool["inputSchema"], "output_schema": tool.get("outputSchema"),
                    "output_kind": "interpretation" if reasoning else "unverified",
                    "enabled": not server.get("tool_confirmation_required", False),
                    "discovered_at": snapshot.get("discovered_at"),
                    "policy": {"read_only": read_only, "idempotent": read_only and not reasoning,
                               "timeout": server.get("timeout", 30), "concurrency": 1,
                               "session_scope": "run" if reasoning else "call"},
                }
                reason = None if server.get("status") == "active" else "Server disabled"
                if server.get("type") == "stdio" and not shutil.which(server.get("command", "")):
                    reason = f"Executable not installed: {server.get('command', '')}"
                self._add(definition, reason, version_of(server))

    def _add(self, definition, reason=None, config_version=None):
        item = deepcopy(definition)
        override = deepcopy(self.settings["tools"].get(item["tool_id"], {}))
        item["policy"].update(override.pop("policy", {}))
        item.update(override)
        if item["output_kind"] == "interpretation":
            item["policy"].update(concurrency=1, session_scope="run", idempotent=False)
        item["available"] = reason is None
        item["unavailable_reason"] = reason
        item["config_version"] = config_version
        item["definition_version"] = version_of({
            key: value for key, value in item.items() if key != "discovered_at"})
        self.entries[item["tool_id"]] = item

    def list(self):
        return deepcopy(list(self.entries.values()))

    def candidates(self, categories=None, capabilities=None, limit=12, query=None, max_bytes=24 * 1024):
        selected = [item for item in self.list()
                if item["enabled"] and item["available"] and item["categories"]
                and (not item.get("compatibility_only") or item["tool_id"] in
                     self.settings["default_providers"].values())
                and item["capabilities"] and item["when_to_use"]
                and (item["policy"]["read_only"] or item["output_kind"] == "interpretation")
                and (not categories or set(item["categories"]) & set(categories))
                and (not capabilities or set(item["capabilities"]) & set(capabilities))]
        if query:
            from utils.semantics import tokens
            wanted = set(tokens(query))
            selected.sort(key=lambda item: -len(
                wanted & set(tokens(item["description"] + " " + item["when_to_use"]))))
        bounded, used = [], 2
        for item in selected:
            size = len(json.dumps({key: item[key] for key in (
                "tool_id", "capabilities", "description", "when_to_use", "input_schema",
                "output_kind", "definition_version", "policy")}, ensure_ascii=False).encode()) + (2 if bounded else 0)
            if used + size <= max_bytes:
                bounded.append(item)
                used += size
            if len(bounded) >= limit:
                break
        return bounded

    def resolve(self, capability, tool_id=None):
        selected = tool_id or self.settings["default_providers"].get(capability)
        if selected:
            item = self.entries.get(selected)
            if item is None or capability not in item["capabilities"]:
                raise ValueError(f"Unknown or incompatible tool binding: {selected} / {capability}")
            if not item["enabled"]:
                raise ValueError(f"Tool disabled: {selected}")
            if not item["available"]:
                raise ValueError(f"Tool unavailable: {selected}: {item['unavailable_reason']}")
            return deepcopy(item)
        matches = [item for item in self.entries.values() if capability in item["capabilities"]
                   and not item.get("compatibility_only") and item["enabled"] and item["available"]]
        if len(matches) != 1:
            raise ValueError(f"Capability {capability} requires an explicit available tool_id; "
                             f"found {len(matches)} providers")
        return deepcopy(matches[0])

def _build_entries(serialized):
    snapshot = json.loads(serialized)
    catalog = ToolCatalog.__new__(ToolCatalog)
    catalog.settings, catalog.servers = snapshot["settings"], snapshot["servers"]
    catalog._populate(snapshot["has_sources"], snapshot["discoveries"])
    return catalog.entries


@lru_cache(maxsize=16)
def _cached_entries(serialized):
    return _build_entries(serialized)


def compatibility_definitions():
    definitions = []
    for item in local_definitions():
        if item["tool_name"].startswith("database."):
            definitions.append({"name": item["tool_name"].replace(".", "_"),
                                "capability": item["tool_name"], "tool_id": item["tool_id"],
                                "description": item["description"], "inputSchema": item["input_schema"]})
    for engine in ("mysql", "athena"):
        properties = {"host": {"type": "string"}, "username": {"type": "string"},
                      "password": {"type": "string"}, "database": {"type": "string"},
                      "region": {"type": "string"}}
        required = ["region"] if engine == "athena" else ["host", "username", "password", "database"]
        connection = {"type": "object", "properties": properties, "required": required}
        for action, parameter, capability in (
                ("query", "sql", "database.query"), ("describe_table", "table_name", "database.metadata")):
            definitions.append({
                "name": f"{engine}_{action}", "description": f"Legacy {engine} {action} compatibility",
                "tool_id": f"local:{capability}",
                "annotations": {"destructiveHint": False, "audience": (
                    ["data_analysts", "business_users"] if engine == "athena" and action == "query" else
                    ["data_analysts", "developers"] if engine == "athena" else
                    ["developers", "data_analysts"] if action == "query" else
                    ["developers", "database_administrators"])},
                "inputSchema": object_schema(
                    {parameter: {"type": "string"}, "config": connection, "database": {"type": "string"}},
                    (parameter, "config")),
            })
    for alias, capability in (("web_fetch", "external.fetch"), ("web_search", "external.search")):
        item = (_definition("external.search", "search", "Find sources, not verified observations.",
                            object_schema({"query": {"type": "string"},
                                           "max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
                                          ("query",)), "discovery")
                if capability == "external.search"
                else next(item for item in local_definitions() if capability in item["capabilities"]))
        definitions.append({"name": alias, "description": item["description"],
                            "annotations": {"destructiveHint": False, "audience": (
                                ["researchers", "analysts", "general_users"] if capability == "external.search"
                                else ["researchers", "content_creators", "analysts"])},
                            "tool_id": ("legacy:playwright:search_web" if capability == "external.search"
                                        else "legacy:playwright:fetch_page"), "inputSchema": item["input_schema"]})
    return definitions
