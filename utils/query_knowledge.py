"""Question-oriented guidance that references, but never grants, run resources."""

from copy import deepcopy

from utils.resource_scope import can_reference, validate_visibility
from utils.semantics import KnowledgeIndex


def validate_query_knowledge(library, config):
    from utils.knowledge_center import validate_stages
    if not isinstance(library, dict) or not isinstance(library.get("queries", []), list):
        raise ValueError("Query knowledge requires a queries list")
    sources = config.load_datasources()
    ontology = config.load_semantics()
    catalogs = {
        "knowledge": {item["id"]: item for item in config.load_knowledge().get("documents", [])},
        "methods": {item["id"]: item for item in config.load_methods().get("methods", [])},
    }
    seen = set()
    for item in library.get("queries", []):
        if (not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k].strip()
                                                for k in ("id", "question", "guidance"))
                or item["id"] in seen):
            raise ValueError("Query knowledge requires a unique ID, typical question and guidance")
        seen.add(item["id"])
        validate_visibility(item, config.load_profiles())
        validate_stages(item, "queries")
        examples = item.get("examples", [])
        if (not isinstance(examples, list) or len(examples) > 8
                or any(not isinstance(example, dict)
                       or set(example) != {"question", "guidance"}
                       or not all(isinstance(example.get(key), str) and example[key].strip()
                                  for key in ("question", "guidance")) for example in examples)):
            raise ValueError("Guides accept up to 8 examples, each with a question and handling guidance")
        bindings = item.get("bindings", {})
        if not isinstance(bindings, dict) or set(bindings) - {"sources", "semantics", "knowledge", "methods"}:
            raise ValueError("Invalid query knowledge bindings")
        if not isinstance(bindings.get("sources", {}), dict):
            raise ValueError("Query source bindings must map datasource IDs to tables")
        for key, tables in bindings.get("sources", {}).items():
            source = sources.get(key)
            if source is None or not can_reference(item, source):
                raise ValueError(f"Query knowledge references an unavailable datasource: {key}")
            if not isinstance(tables, list) or not tables or any(not isinstance(t, str) for t in tables):
                raise ValueError("Query knowledge must select saved tables")
            for table in tables:
                if (table not in source["schema"].get("tables", {})
                        or not can_reference(item, source["schema"].get("table_scopes", {}).get(table, {}))):
                    raise ValueError(f"Query knowledge references an unavailable table: {table}")
        semantics = bindings.get("semantics", {})
        if not isinstance(semantics, dict) or set(semantics) - {"metrics", "entities", "dimensions"}:
            raise ValueError("Invalid query semantic bindings")
        for kind, ids in {**semantics, **{k: bindings.get(k, []) for k in catalogs}}.items():
            catalog = catalogs.get(kind, ontology.get(kind, {}))
            if not isinstance(ids, list) or any(not isinstance(key, str) for key in ids):
                raise ValueError("Query resource bindings require ID lists")
            for key in ids:
                if key not in catalog or not can_reference(item, catalog[key]):
                    raise ValueError(f"Query knowledge references an unavailable {kind} resource: {key}")
    return library


def query_available(item, sources, ontology, knowledge_ids, method_ids):
    bindings = item.get("bindings", {})
    return (
        all(key in sources and set(tables) <= set(sources[key]["schema"].get("tables", {}))
            for key, tables in bindings.get("sources", {}).items())
        and all(set(ids) <= set(ontology.get(kind, {})) for kind, ids in bindings.get("semantics", {}).items())
        and set(bindings.get("knowledge", [])) <= set(knowledge_ids)
        and set(bindings.get("methods", [])) <= set(method_ids)
    )


def retrieve_query_guidance(config, question, stage=None):
    from utils.knowledge_center import stages_for
    library = config.load_query_knowledge()
    items = {item["id"]: item for item in library.get("queries", [])
             if stage is None or stage in stages_for(item, "queries")}
    docs = [{"id": item["id"], "title": item["question"],
             "text": item["question"] + "\n" + item["guidance"] + "\n" + "\n".join(
                 example["question"] + "\n" + example["guidance"] for example in item.get("examples", [])),
             "source": f"query-knowledge:{item['id']}", "version": "1", "scope": "*"} for item in items.values()]
    matches = KnowledgeIndex({"documents": docs}).search(question, limit=6)
    selected = list(dict.fromkeys(match["id"] for match in matches))[:3]
    result = []
    for key in selected:
        item = items[key]
        knowledge_ids = item.get("bindings", {}).get("knowledge", [])
        knowledge = {"documents": [doc for doc in config.load_knowledge().get("documents", [])
                                  if doc["id"] in knowledge_ids and (stage is None or stage in stages_for(doc, "documents"))]}
        result.append({**{field: deepcopy(item[field]) for field in (
            "id", "question", "guidance", "bindings", "examples") if field in item},
            "knowledge_excerpts": KnowledgeIndex(knowledge).chunks[:4]})
    return result
