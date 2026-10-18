import json
import math
import re
import hashlib
from collections import Counter
from copy import deepcopy
from functools import lru_cache


def parse_json(text):
    block = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    try:
        result = json.loads(block.group(1) if block else text)
    except (ValueError, TypeError) as exc:
        raise ValueError("Model returned invalid structured JSON") from exc
    if not isinstance(result, dict):
        raise ValueError("Structured output must be an object")
    return result


def validate_ontology(ontology, sources):
    from utils.resource_scope import can_reference, validate_visibility
    from utils.knowledge_center import validate_stages
    if not isinstance(ontology, dict) or set(ontology) - {"version", "entities", "metrics", "dimensions", "relations"}:
        raise ValueError("Invalid ontology fields")
    for kind in ("entities", "metrics", "dimensions"):
        items = ontology.get(kind, {})
        if not isinstance(items, dict):
            raise ValueError(f"{kind} must be keyed by stable IDs")
        for identifier, item in items.items():
            if (not isinstance(identifier, str) or not identifier.strip() or not isinstance(item, dict)
                    or not isinstance(item.get("description"), str) or not item["description"].strip()):
                raise ValueError(f"{kind} requires ID and description")
            validate_visibility(item)
            validate_stages(item, kind)
            for field in ("name", "subject", "dimension_notes"):
                if field in item and not isinstance(item[field], str):
                    raise ValueError(f"Business definition {field} must be text")
            if "name" in item and not item["name"].strip():
                raise ValueError("Business definition name must not be empty")
            for field, target_kind in (("entity_ids", "entities"), ("dimension_ids", "dimensions")):
                ids = item.get(field, [])
                targets = ontology.get(target_kind, {})
                if (not isinstance(ids, list) or any(not isinstance(key, str) for key in ids)
                        or len(set(ids)) != len(ids) or set(ids) - set(targets)):
                    raise ValueError(f"Invalid business definition references: {field}")
                if any(not can_reference(item, targets[key]) for key in ids):
                    raise ValueError("Business definition references must have compatible visibility")
            if kind == "metrics":
                for field in ("formula", "aggregation", "time_field", "unit", "numerator", "denominator"):
                    if field in item and not isinstance(item[field], str):
                        raise ValueError(f"Metric {identifier} {field} must be text")
                dimensions = item.get("allowed_dimensions", [])
                if not isinstance(dimensions, list) or any(not isinstance(d, str) for d in dimensions):
                    raise ValueError(f"Metric {identifier} dimensions must be a list of IDs")
                unknown = set(dimensions) - set(ontology.get("dimensions", {}))
                if unknown:
                    raise ValueError(f"Unknown metric dimensions: {sorted(unknown)}")
                if any(not can_reference(item, ontology["dimensions"][dimension]) for dimension in dimensions):
                    raise ValueError("Metric dimensions must be shared or belong to the same Profile")
            if not isinstance(item.get("mappings", {}), dict):
                raise ValueError(f"{kind} mappings must be an object")
            for source_id, binding in item.get("mappings", {}).items():
                if not isinstance(binding, dict):
                    raise ValueError(f"Invalid datasource mapping: {source_id}")
                if source_id not in sources:
                    raise ValueError(f"Unknown datasource mapping: {source_id}")
                if not can_reference(item, sources[source_id]):
                    raise ValueError("A shared business definition cannot bind a private datasource")
                schema = sources[source_id].get("schema", {}).get("tables", {})
                table = binding.get("table")
                if table not in schema:
                    raise ValueError(f"Unknown table in mapping: {source_id}/{table}")
                if not can_reference(item, sources[source_id]["schema"].get("table_scopes", {}).get(table, {})):
                    raise ValueError("A shared business definition cannot bind a private table schema")
                info = schema[table]
                columns = info.get("columns", []) if isinstance(info, dict) else info
                selected_columns = binding.get("columns", [])
                if (not isinstance(selected_columns, list)
                        or any(not isinstance(name, str) or name not in {c["name"] for c in columns}
                               for name in selected_columns)):
                    raise ValueError(f"Unknown column in mapping: {identifier}")
    for relation in ontology.get("relations", []):
        if relation.get("from") not in ontology.get("entities", {}) or relation.get("to") not in ontology.get("entities", {}):
            raise ValueError("Ontology relations must reference known entities")
    return ontology


def validate_knowledge(knowledge):
    from utils.knowledge_center import validate_stages
    if not isinstance(knowledge, dict) or not isinstance(knowledge.get("documents", []), list):
        raise ValueError("Knowledge requires a documents list")
    ids = set()
    for doc in knowledge.get("documents", []):
        validate_stages(doc, "documents")
        if not all(isinstance(doc.get(key), str) and doc[key].strip()
                   for key in ("id", "title", "text", "source", "version", "scope")):
            raise ValueError("Knowledge document requires id, title, text, source, version and scope")
        if doc["id"] in ids:
            raise ValueError("Duplicate knowledge document ID")
        ids.add(doc["id"])
    return knowledge


def configuration_examples(sources):
    mappings = {}
    time_field = ""
    for identifier, source in sources.items():
        for table, info in source.get("schema", {}).get("tables", {}).items():
            columns = info.get("columns", []) if isinstance(info, dict) else info
            mappings[identifier] = {"table": table, "columns": [columns[0]["name"]] if columns else []}
            time_field = next((column["name"] for column in columns
                               if any(kind in str(column.get("type", "")).lower() for kind in ("date", "time"))), "")
            break
        if mappings:
            break
    return {
        "ontology": {"version": 1, "entities": {}, "dimensions": {}, "relations": [], "metrics": {
            "kpi1": {"description": "KPI1 = A * B * C per order line. A is unit price, B is quantity, C is the discount factor."},
            "record_count": {"description": "Count records in the selected table; replace with your business definition.",
                             "formula": "COUNT(*)", "aggregation": "count", "time_field": time_field, "unit": "records",
                             "allowed_dimensions": [], "mappings": mappings}}},
        "knowledge": {"documents": [
            {"id": "example-definition", "title": "Revenue definition", "source": "business-manual#revenue",
             "version": "1", "scope": "sales", "text": "Revenue excludes refunded orders. Replace with your approved definition."}]},
        "methods": {"methods": [{
            "id": "example-comparison", "title": "Compare a metric", "description": "Compare the same metric over comparable periods.",
            "version": 1, "status": "draft", "preconditions": {"has_time": True},
            "required_capabilities": ["database.query", "llm.analysis"],
            "template": {"steps": [
                {"step_id": 1, "step_type": "sql_query", "description": "Query the metric for both periods", "dependencies": []},
                {"step_id": 2, "step_type": "llm_analysis", "description": "Compare the evidence",
                 "dependencies": [1], "analysis_requirements": {"input_data": [1]}}]},
            "cases": [{"id": "example-case", "status": "draft", "problem_structure": "Why did the metric change?",
                       "required_data": "Comparable metric totals", "adaptation": "Bind current tables and dates",
                       "limitations": "Comparison alone cannot prove causality"}],
        }]},
    }


def tokens(text):
    words = re.findall(r"[a-z0-9_]+", text.lower())
    for part in re.findall(r"[\u4e00-\u9fff]+", text):
        words.extend(part[i:i + 2] for i in range(max(len(part) - 1, 1)))
    return Counter(words)


def _build_knowledge(serialized):
    chunks, terms, postings = [], [], {}
    for doc in json.loads(serialized).get("documents", []):
        for i, start in enumerate(range(0, len(doc["text"]), 800)):
            chunk = {key: value for key, value in doc.items() if key != "text"}
            chunk.update(chunk_id=f"{doc['id']}:{i}", text=doc["text"][start:start + 900],
                         position=start)
            index = len(chunks)
            chunk_terms = tokens(chunk["title"] + " " + chunk["text"])
            for term in chunk_terms:
                postings.setdefault(term, []).append(index)
            chunks.append(chunk)
            terms.append(chunk_terms)
    weights = {term: math.log(1 + len(terms) / (1 + len(indices))) for term, indices in postings.items()}
    return chunks, terms, postings, weights


@lru_cache(maxsize=8)
def _cached_knowledge(serialized):
    return _build_knowledge(serialized)


class KnowledgeIndex:
    def __init__(self, knowledge):
        validate_knowledge(knowledge)
        serialized = json.dumps(knowledge, sort_keys=True, ensure_ascii=False)
        self.version = hashlib.sha256(("chunks-800-900:tokens-v1:" + serialized).encode()).hexdigest()
        # Oversized corpora remain searchable without occupying the shared cache.
        build = _cached_knowledge if len(serialized.encode()) <= 4 * 1024 * 1024 else _build_knowledge
        self._chunks, self._terms, self._postings, self._weights = build(serialized)

    @property
    def chunks(self):
        return deepcopy(self._chunks)

    @staticmethod
    def cache_info():
        return _cached_knowledge.cache_info()

    def search(self, query, limit=4, scope=None):
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("Knowledge search limit must be from 1 to 20")
        query_terms = tokens(query)
        results = []
        candidates = sorted({index for term in query_terms for index in self._postings.get(term, [])})
        for index in candidates:
            chunk, terms = self._chunks[index], self._terms[index]
            if scope and chunk["scope"] not in (scope, "*"):
                continue
            score = sum(min(count, terms.get(term, 0)) * self._weights.get(term, 0)
                        for term, count in query_terms.items())
            if score:
                results.append({**deepcopy(chunk), "score": score})
        return sorted(results, key=lambda item: (-item["score"], item["chunk_id"]))[:limit]
