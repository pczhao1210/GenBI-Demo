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
    if not isinstance(ontology, dict) or set(ontology) - {"version", "entities", "metrics", "dimensions", "relations"}:
        raise ValueError("Invalid ontology fields")
    for kind in ("entities", "metrics", "dimensions"):
        items = ontology.get(kind, {})
        if not isinstance(items, dict):
            raise ValueError(f"{kind} must be keyed by stable IDs")
        for identifier, item in items.items():
            if not identifier or not isinstance(item, dict) or not item.get("description"):
                raise ValueError(f"{kind} requires ID and description")
            if kind == "metrics":
                required = {"formula", "aggregation", "time_field", "unit", "allowed_dimensions", "mappings"}
                if not required <= item.keys():
                    raise ValueError(f"Metric {identifier} is missing {sorted(required - item.keys())}")
                unknown = set(item["allowed_dimensions"]) - set(ontology.get("dimensions", {}))
                if unknown:
                    raise ValueError(f"Unknown metric dimensions: {sorted(unknown)}")
            for source_id, binding in item.get("mappings", {}).items():
                if source_id not in sources:
                    raise ValueError(f"Unknown datasource mapping: {source_id}")
                schema = sources[source_id].get("schema", {}).get("tables", {})
                table = binding.get("table")
                if table not in schema:
                    raise ValueError(f"Unknown table in mapping: {source_id}/{table}")
                info = schema[table]
                columns = info.get("columns", []) if isinstance(info, dict) else info
                if any(name not in {c["name"] for c in columns} for name in binding.get("columns", [])):
                    raise ValueError(f"Unknown column in mapping: {identifier}")
    for relation in ontology.get("relations", []):
        if relation.get("from") not in ontology.get("entities", {}) or relation.get("to") not in ontology.get("entities", {}):
            raise ValueError("Ontology relations must reference known entities")
    return ontology


def validate_knowledge(knowledge):
    if not isinstance(knowledge, dict) or not isinstance(knowledge.get("documents", []), list):
        raise ValueError("Knowledge requires a documents list")
    ids = set()
    for doc in knowledge.get("documents", []):
        if not all(isinstance(doc.get(key), str) and doc[key].strip()
                   for key in ("id", "title", "text", "source", "version", "scope")):
            raise ValueError("Knowledge document requires id, title, text, source, version and scope")
        if doc["id"] in ids:
            raise ValueError("Duplicate knowledge document ID")
        ids.add(doc["id"])
    return knowledge


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
