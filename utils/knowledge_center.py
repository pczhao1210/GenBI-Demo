"""Unified catalog and stage-specific context over the existing knowledge stores."""

from copy import deepcopy
import json
from urllib.parse import quote

from utils.resource_scope import resource_visibility
from utils.semantics import KnowledgeIndex

STAGES = ("understanding", "planning", "sql_generation", "analysis", "explanation")
DEFAULT_STAGES = {
    "metrics": STAGES, "entities": STAGES, "dimensions": STAGES,
    "queries": ("understanding", "planning", "sql_generation", "analysis"),
    "methods": ("planning", "analysis"), "cases": ("planning", "analysis"),
    "documents": STAGES,
}
FAMILIES = {**{kind: "definitions" for kind in ("metrics", "entities", "dimensions")},
            **{kind: "guides" for kind in ("queries", "methods", "cases")}, "documents": "references"}
PINNED_STAGES = ("understanding", "planning", "sql_generation")


def stages_for(item, kind):
    return item.get("retrieval_stages", list(DEFAULT_STAGES[kind]))


def validate_stages(item, kind):
    stages = stages_for(item, kind)
    if (not isinstance(stages, (list, tuple)) or any(not isinstance(stage, str) for stage in stages)
            or len(set(stages)) != len(stages) or set(stages) - set(DEFAULT_STAGES[kind])):
        raise ValueError(f"Invalid retrieval stages for {kind}")


def definition_name(identifier, item):
    return item.get("name") or identifier


def entry_key(kind, identifier, parent=None):
    return f"{kind}:{quote(parent, safe='') + ':' if parent else ''}{quote(identifier, safe='')}"


def catalog_entries(config):
    entries = []

    def add(kind, identifier, item, title, parent=None):
        entries.append({"key": entry_key(kind, identifier, parent), "kind": kind, "id": identifier,
                        "parent": parent, "family": FAMILIES[kind], "title": title,
                        "visibility": resource_visibility(item), "stages": list(stages_for(item, kind)),
                        "status": item.get("status"), "record": deepcopy(item)})

    for kind in ("metrics", "entities", "dimensions"):
        for identifier, item in config.load_semantics().get(kind, {}).items():
            add(kind, identifier, item, definition_name(identifier, item))
    for item in config.load_query_knowledge().get("queries", []):
        add("queries", item["id"], item, item["question"])
    for item in config.load_methods().get("methods", []):
        add("methods", item["id"], item, item["title"])
        for case in item.get("cases", []):
            title = case.get("problem_structure", case["id"])
            add("cases", case["id"], case, title if isinstance(title, str) else json.dumps(title, ensure_ascii=False),
                item["id"])
    for item in config.load_knowledge().get("documents", []):
        add("documents", item["id"], item, item["title"])
    return entries


def execution_config(config):
    from utils.run_context import FrozenConfig, snapshot_config
    return config if isinstance(config, FrozenConfig) else FrozenConfig(
        snapshot_config(config, getattr(config, "profile_id", None)))


def planning_conditions(config, question):
    metrics = [item for identifier, item in config.load_semantics().get("metrics", {}).items() if identifier in question]
    return {"has_components": any(item.get("numerator") and item.get("denominator") for item in metrics),
            "has_time": '"time"' in question}


def knowledge_context(config, question, stage, *, capabilities=None, conditions=None):
    from utils.analysis import MethodLibrary
    from utils.query_knowledge import retrieve_query_guidance
    from utils.tool_catalog import ToolCatalog
    if stage not in STAGES:
        raise ValueError(f"Unsupported knowledge stage: {stage}")
    config = execution_config(config)
    guides = retrieve_query_guidance(config, question, stage=stage)
    methods = []
    if stage in DEFAULT_STAGES["methods"]:
        if capabilities is None:
            capabilities = {cap for tool in ToolCatalog(config).candidates(query=question) for cap in tool["capabilities"]}
        methods = MethodLibrary(config.load_methods()).retrieve(
            question, set(capabilities) | {"llm.analysis"},
            planning_conditions(config, question) if conditions is None else conditions,
            preferred_ids=[key for guide in guides for key in guide.get("bindings", {}).get("methods", [])],
            stage=stage)
    docs = [doc for doc in config.load_knowledge().get("documents", []) if stage in stages_for(doc, "documents")]
    if stage == "explanation":
        ontology = config.load_semantics()
        for kind in ("entities", "metrics", "dimensions"):
            for identifier, item in ontology.get(kind, {}).items():
                if stage in stages_for(item, kind):
                    docs.append({"id": f"ontology-{identifier}", "title": definition_name(identifier, item),
                                 "text": json.dumps(item, ensure_ascii=False), "source": "ontology",
                                 "version": str(ontology.get("version", 1)), "scope": "*"})
    return {"stage": stage, "guides": guides, "methods": methods,
            "documents": KnowledgeIndex({"documents": docs}).search(question, limit=4)}


def preview_knowledge(config, question, stage):
    frozen = execution_config(config)
    context = knowledge_context(frozen, question, stage)
    available = catalog_entries(frozen)
    used = {entry_key("queries", item["id"]) for item in context["guides"]}
    used.update(entry_key("methods", item["id"]) for item in context["methods"])
    used.update(entry_key("documents", item["id"]) for item in context["documents"] if item["source"] != "ontology")
    for guide in context["guides"]:
        used.update(entry_key("documents", item["id"]) for item in guide["knowledge_excerpts"])
    for method in context["methods"]:
        used.update(entry_key("cases", item["id"], method["id"]) for item in method.get("cases", []))
    rows = []
    for entry in available:
        pinned = entry["family"] == "definitions" and stage in PINNED_STAGES
        matched = entry["key"] in used or (
            entry["family"] == "definitions"
            and any(doc["source"] == "ontology" and doc["id"] == f"ontology-{entry['id']}"
                    for doc in context["documents"]))
        if pinned or matched:
            rows.append({key: entry[key] for key in ("key", "title", "kind", "visibility")} |
                        {"reason": "pinned" if pinned else "matched", "stage": stage})
    available_keys = {entry["key"] for entry in available}
    excluded = []
    for entry in catalog_entries(config):
        if entry["key"] in available_keys:
            continue
        missing = []
        if entry["kind"] == "queries":
            bindings = entry["record"].get("bindings", {})
            sources = frozen.load_datasources()
            for source, tables in bindings.get("sources", {}).items():
                for table in tables:
                    if table not in sources.get(source, {}).get("schema", {}).get("tables", {}):
                        missing.append(f"{source}/{table}")
            for binding, kind in (("knowledge", "documents"), ("methods", "methods")):
                missing.extend(identifier for identifier in bindings.get(binding, [])
                               if entry_key(kind, identifier) not in available_keys)
            for kind, ids in bindings.get("semantics", {}).items():
                missing.extend(identifier for identifier in ids if entry_key(kind, identifier) not in available_keys)
        excluded.append({"title": entry["title"], "kind": entry["kind"], "missing": missing})
    return {"context": context, "used": rows, "outside_run_scope": excluded}
