"""Business resource scopes, applied before planning and frozen for each run."""

from copy import deepcopy
from utils.resource_scope import filter_ontology, filter_source, filter_workflow, table_visible, visible
from utils.query_knowledge import query_available


def validate_profile(profile, snapshot):
    if not isinstance(profile, dict) or not all(
            isinstance(profile.get(key), str) and profile[key].strip() for key in ("id", "name")):
        raise ValueError("Profile requires an ID and a name")
    bindings = profile.get("datasources")
    if profile.get("status", "active") not in ("draft", "active"):
        raise ValueError("Profile status must be draft or active")
    draft = profile.get("status") == "draft"
    if not isinstance(bindings, dict) or (not bindings and not draft):
        raise ValueError("Profile requires at least one datasource and selected tables")
    for identifier, tables in bindings.items():
        source = snapshot["sources"].get(identifier)
        if source is None or not visible(source, profile["id"]):
            raise ValueError(f"Profile datasource no longer exists: {identifier}")
        if (not isinstance(tables, list) or (not tables and not draft) or any(not isinstance(t, str) for t in tables)
                or len(set(tables)) != len(tables)):
            raise ValueError(f"Select at least one table for {identifier}")
        missing = set(tables) - set(source["schema"].get("tables", {}))
        if missing:
            raise ValueError(f"Profile tables no longer exist: {identifier}: {sorted(missing)}")
        if any(not table_visible(source, table, profile["id"]) for table in tables):
            raise ValueError(f"Profile references a table schema owned by another Profile: {identifier}")
    resources = {
        "mcp_servers": set(snapshot["mcp"]),
        "knowledge_ids": {doc["id"] for doc in snapshot["knowledge"].get("documents", []) if visible(doc, profile["id"])},
        "method_ids": {method["id"] for method in snapshot["methods"].get("methods", []) if visible(method, profile["id"])},
        "query_ids": {item["id"] for item in snapshot.get("query_knowledge", {}).get("queries", [])
                      if visible(item, profile["id"])},
    }
    for key, available in resources.items():
        selected = profile.get(key, [])
        if (not isinstance(selected, list) or any(not isinstance(item, str) for item in selected)
                or len(set(selected)) != len(selected) or set(selected) - available):
            raise ValueError(f"Profile has invalid or missing resources: {key}")
    selected_sources = {
        key: {**snapshot["sources"][key], "schema": {"tables": {
            table: snapshot["sources"][key]["schema"]["tables"][table] for table in tables}}}
        for key, tables in bindings.items()}
    semantics = filter_ontology(snapshot["semantics"], selected_sources, profile["id"])
    for item in snapshot.get("query_knowledge", {}).get("queries", []):
        if item["id"] in profile.get("query_ids", []) and not query_available(
                item, selected_sources, semantics, profile.get("knowledge_ids", []), profile.get("method_ids", [])):
            raise ValueError(f"Query knowledge requires resources not selected in this Profile: {item['question']}")
    return profile


def scope_snapshot(snapshot, profile):
    validate_profile(profile, snapshot)
    if profile.get("status") == "draft":
        raise ValueError("This Profile is a draft; select its resources and activate it before querying")
    result = deepcopy(snapshot)
    result["resource_scoped"] = True
    result["profile"] = deepcopy(profile)
    result["workflow"] = filter_workflow(result["workflow"], profile["id"])
    result["sources"] = {}
    for identifier, tables in profile["datasources"].items():
        source = deepcopy(snapshot["sources"][identifier])
        schema = source["schema"]
        source["schema"] = {
            **schema,
            "tables": {table: schema["tables"][table] for table in tables},
            "descriptions": {table: schema.get("descriptions", {}).get(table, "") for table in tables},
        }
        if "table_scopes" in schema:
            source["schema"]["table_scopes"] = {key: value for key, value in schema["table_scopes"].items() if key in tables}
        result["sources"][identifier] = source
    result["schemas"] = {identifier: source["schema"] for identifier, source in result["sources"].items()}
    result["databases"] = {}
    # MySQL/Athena scripts are transport adapters, not optional business tools.
    adapters = {source["engine"] for source in result["sources"].values()} & {"mysql", "athena"}
    allowed_servers = set(profile.get("mcp_servers", [])) | adapters
    result["mcp"] = {key: value for key, value in snapshot["mcp"].items() if key in allowed_servers}
    result["tool_discovery"]["servers"] = {
        key: value for key, value in snapshot["tool_discovery"].get("servers", {}).items()
        if key in allowed_servers}
    result["knowledge"]["documents"] = [
        doc for doc in snapshot["knowledge"].get("documents", []) if doc["id"] in profile.get("knowledge_ids", [])]
    result["methods"]["methods"] = [
        method for method in snapshot["methods"].get("methods", []) if method["id"] in profile.get("method_ids", [])]
    for method in result["methods"]["methods"]:
        if "cases" in method:
            method["cases"] = [case for case in method["cases"] if visible(case, profile["id"])]
    result["semantics"] = filter_ontology(result["semantics"], result["sources"], profile["id"])
    result["query_knowledge"] = {"queries": [
        item for item in snapshot.get("query_knowledge", {}).get("queries", []) if item["id"] in profile.get("query_ids", [])]}
    return result


def shared_snapshot(snapshot):
    result = deepcopy(snapshot)
    result["resource_scoped"] = True
    result["sources"] = {key: filter_source(source, None) for key, source in result["sources"].items() if visible(source, None)}
    result["schemas"] = {key: source["schema"] for key, source in result["sources"].items()}
    result["databases"] = {}
    for engine in {source["engine"] for source in result["sources"].values()}:
        matches = [source for source in result["sources"].values() if source["engine"] == engine]
        if len(matches) == 1:
            result["databases"][engine] = matches[0]["config"]
            result["schemas"][engine] = matches[0]["schema"]
    result["semantics"] = filter_ontology(result["semantics"], result["sources"], None)
    result["knowledge"]["documents"] = [doc for doc in result["knowledge"].get("documents", []) if visible(doc, None)]
    result["methods"]["methods"] = [method for method in result["methods"].get("methods", []) if visible(method, None)]
    for method in result["methods"]["methods"]:
        if "cases" in method:
            method["cases"] = [case for case in method["cases"] if visible(case, None)]
    result["workflow"] = filter_workflow(result["workflow"], None)
    result["query_knowledge"] = {"queries": [
        item for item in result.get("query_knowledge", {}).get("queries", [])
        if visible(item, None) and query_available(
            item, result["sources"], result["semantics"],
            [doc["id"] for doc in result["knowledge"]["documents"]],
            [method["id"] for method in result["methods"]["methods"]])]}
    return result
