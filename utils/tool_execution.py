"""Validated tool invocation over frozen catalog and datasource definitions."""

import time
from jsonschema import Draft202012Validator, ValidationError

from utils.datasources import DatabaseAdapter
from utils.tool_catalog import ToolCatalog, matches_definition_version, version_of
from utils.resources import tool_resources
from utils.mcp_client import MCPClient
from utils.datasources import serialize_cell
import json


class ToolInvoker:
    def __init__(self, config, mcp, budget, active_sources=None, live_config=None):
        self.config = config
        self.mcp = mcp
        self.budget = budget
        self.catalog = ToolCatalog(config)
        self.active_sources = active_sources
        self.live_config = live_config or config
        self.cancelled = lambda: False
        self.deadline = None

    def resolve(self, capability, tool_id=None):
        if ((not tool_id or tool_id in self.catalog.entries)
                and any(capability in item["capabilities"] for item in self.catalog.entries.values())):
            return self.catalog.resolve(capability, tool_id)
        # Old exact capability mappings predate tools/list snapshots. They remain
        # callable, but are never exposed as discovered planner candidates.
        selected = tool_id or self.catalog.settings["default_providers"].get(capability)
        matches = [(server_id, server, server["capabilities"][capability])
                   for server_id, server in self.catalog.servers.items()
                   if server.get("protocol") == "mcp" and not server.get("tool_confirmation_required", False)
                   and server.get("status") == "active" and isinstance(server.get("capabilities"), dict)
                   and capability in server["capabilities"]
                   and (not selected or selected == f"mcp:{server_id}:{server['capabilities'][capability]}")]
        if len(matches) != 1:
            raise ValueError(f"Capability {capability} requires one explicit active provider, found {len(matches)}")
        server_id, server, tool_name = matches[0]
        identity = f"mcp:{server_id}:{tool_name}"
        return {"tool_id": identity, "backend": "mcp", "server_id": server_id, "tool_name": tool_name,
                "capabilities": [capability], "input_schema": {"type": "object"}, "output_kind": "unverified",
                "definition_version": version_of({"server": server, "tool": tool_name}),
                "policy": {"read_only": True, "idempotent": False, "timeout": server.get("timeout", 30),
                           "concurrency": 1, "session_scope": "call"}}

    def legacy_binding(self, capability):
        selected = self.catalog.settings["default_providers"].get(capability)
        if selected:
            return selected
        matches = [f"mcp:{server_id}:{server['capabilities'][capability]}"
                   for server_id, server in self.catalog.servers.items()
                   if server.get("protocol") == "mcp" and not server.get("tool_confirmation_required", False)
                   and server.get("status") == "active" and isinstance(server.get("capabilities"), dict)
                   and capability in server["capabilities"]]
        if len(matches) > 1:
            raise ValueError(f"Capability {capability} requires an explicit default provider")
        return matches[0] if matches else None

    def call(self, capability, arguments, tool_id=None, definition_version=None, results=None):
        definition = self.resolve(capability, tool_id)
        if definition_version and not matches_definition_version(definition, definition_version):
            raise ValueError("Tool definition version changed; revise the plan explicitly")
        definition["selected_capability"] = capability
        live = self.live_config.load_tools_config()
        if not live["tools"].get(definition["tool_id"], {}).get("enabled", True):
            raise ValueError(f"Tool disabled: {definition['tool_id']}")
        server_id = definition.get("server_id")
        if server_id and self.live_config.load_mcp_config().get(server_id, {}).get("status") != "active":
            raise ValueError(f"Tool server disabled: {server_id}")
        try:
            Draft202012Validator(definition["input_schema"]).validate(arguments)
        except ValidationError as exc:
            raise ValueError(f"Invalid tool parameters: {exc.message}") from exc
        if not definition["policy"]["read_only"] and definition["output_kind"] != "interpretation":
            raise ValueError("Tool policy does not permit read-only execution")
        if capability.startswith("database."):
            if not isinstance(arguments.get("datasource_id"), str):
                raise ValueError("Database tools require an explicit datasource_id")
            source = self.config.resolve_datasource(arguments["datasource_id"])
            definition["resource_provider"] = (source["engine"] if source["engine"] in ("mysql", "athena")
                                               else f"database:{source['datasource_id']}")
            if self.active_sources is not None and source["datasource_id"] not in {
                    self.config.resolve_datasource(identifier)["datasource_id"] for identifier in self.active_sources}:
                raise ValueError("Tool datasource is outside the frozen active set")
        if capability.startswith("compute."):
            refs = arguments.get("inputs")
            if not isinstance(refs, list) or any(type(ref) is not int for ref in refs):
                raise ValueError("Computation requires exact dependency step IDs")
            if not results or any(ref not in results or results[ref].get("status") != "success" for ref in refs):
                raise ValueError("Computation can only reference completed declared dependencies")
        return self._permitted_call(definition, self._execute, definition, arguments, results)

    def compatibility_call(self, tool_definition, function, tool_name, arguments):
        definition = self.catalog.entries[tool_definition["tool_id"]]
        definition = {**definition, "server_id": tool_name.split("_", 1)[0]}
        if definition["server_id"] == "web":
            definition["server_id"] = "playwright"
        return self._permitted_call(definition, function, tool_name, arguments,
                                    timeout=definition["policy"]["timeout"])

    def _permitted_call(self, definition, function, *arguments, **kwargs):
        server_id = definition.get("server_id")
        policy = definition["policy"]
        if not policy["read_only"] and definition["output_kind"] != "interpretation":
            raise ValueError("Tool policy does not permit read-only execution")
        provider = definition.get("resource_provider") or server_id or definition["tool_id"]
        remaining = self.deadline - time.monotonic() if self.deadline else policy["timeout"]
        if remaining <= 0:
            raise RuntimeError("Tool active time budget exhausted")
        with tool_resources.acquire(provider, policy["concurrency"], min(policy["timeout"], remaining), self.cancelled):
            if self.deadline and time.monotonic() >= self.deadline:
                raise RuntimeError("Tool active time budget exhausted")
            if not self.live_config.load_tools_config()["tools"].get(definition["tool_id"], {}).get("enabled", True):
                raise ValueError(f"Tool disabled: {definition['tool_id']}")
            if server_id and self.live_config.load_mcp_config().get(server_id, {}).get("status") != "active":
                raise ValueError(f"Tool server disabled: {server_id}")
            def checked():
                result = function(*arguments, **kwargs)
                if len(json.dumps(serialize_cell(result), ensure_ascii=False).encode()) > 16 * 1024 * 1024:
                    raise RuntimeError("Tool result exceeds the 16 MiB serialization budget")
                return result
            return self.budget.call(definition.get("selected_capability", definition["capabilities"][0]), checked,
                                    _tool_metadata={"tool_id": definition["tool_id"],
                                                    "definition_version": definition["definition_version"]})

    def _execute(self, definition, arguments, results):
        capability = definition.get("selected_capability", definition["capabilities"][0])
        if definition["backend"] in ("mcp", "legacy_rpc"):
            if isinstance(self.mcp, MCPClient):
                response = self.mcp.call_mcp_server(
                    definition["server_id"], definition["tool_name"], arguments,
                    timeout=definition["policy"]["timeout"], exact=True,
                    reuse_session=definition["policy"]["session_scope"] == "run")
            else:
                response = self.mcp.call_mcp_server(definition["server_id"], definition["tool_name"], arguments)
            from utils.bi_service import result_payload
            payload = result_payload(response)
            if definition.get("output_schema"):
                try:
                    Draft202012Validator(definition["output_schema"]).validate(payload)
                except ValidationError as exc:
                    raise RuntimeError(f"MCP output contract failed: {exc.message}") from exc
            if definition["output_kind"] == "interpretation":
                return {"evidence_class": "interpretation", **{
                    key: payload[key] for key in ("thoughtNumber", "totalThoughts", "nextThoughtNeeded")
                    if key in payload}}
            if capability == "external.fetch":
                from utils.external_evidence import mcp_document
                known = self.catalog.servers[definition["server_id"]].get("template") == "fetch"
                return mcp_document(payload, arguments["url"], known,
                                    start_index=arguments.get("start_index", 0))
            return payload
        if capability.startswith("database."):
            source = self.config.resolve_datasource(arguments["datasource_id"])
            query_timeout = source["config"].get("query_timeout", 240)
            if (isinstance(query_timeout, bool) or not isinstance(query_timeout, (int, float))
                    or query_timeout <= 0):
                raise ValueError("Datasource query_timeout must be positive")
            source["config"] = {**source["config"], "query_timeout": min(
                query_timeout, definition["policy"]["timeout"])}
            adapter = DatabaseAdapter(source, self.mcp, call_timeout=definition["policy"]["timeout"])
            if capability == "database.query":
                return adapter.query(arguments["sql"])
            if capability == "database.preview":
                result = adapter.preview(arguments["table"], arguments.get("limit", 20))
                result["data"].update(completeness="SAMPLE", truncated=True)
                result["data"]["warnings"].append("Preview is a sample, not a complete query result.")
                return result
            return adapter.metadata(arguments.get("table"))
        if capability == "knowledge.search":
            from utils.semantics import KnowledgeIndex
            return {"status": "success", "evidence_class": "knowledge", "data": {
                "chunks": KnowledgeIndex(self.config.load_knowledge()).search(**arguments)}}
        if capability.startswith("compute."):
            from utils.computation import compute
            return compute({**arguments, "operation": capability.split(".", 1)[1]}, results)
        if capability == "external.fetch":
            from utils.external_evidence import fetch_document
            return fetch_document(arguments["url"])
        raise ValueError(f"Unsupported local capability: {capability}")
