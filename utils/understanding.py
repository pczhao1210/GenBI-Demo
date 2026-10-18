import json
from copy import deepcopy
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from utils.semantics import parse_json

SLOTS = {"entities", "metrics", "dimensions", "filters", "time", "comparison", "result_reference"}


def resolve_time(value, requested_at, timezone, business_day_start=0):
    zone = ZoneInfo(timezone)
    anchor = datetime.fromisoformat(requested_at).astimezone(zone)
    expression = value.get("expression")
    relative = {"今天": 0, "昨天": 1, "前天": 2, "today": 0, "yesterday": 1,
                "day before yesterday": 2}
    if expression in relative:
        business_date = (anchor - timedelta(hours=business_day_start)).date()
        start = datetime.combine(business_date - timedelta(days=relative[expression]),
                                 time(hour=business_day_start), zone)
        end = start + timedelta(days=1)
    else:
        if not value.get("start") or not value.get("end"):
            raise ValueError("Time must use a supported relative expression or explicit start/end")
        start, end = datetime.fromisoformat(value["start"]), datetime.fromisoformat(value["end"])
        start = start.replace(tzinfo=zone) if start.tzinfo is None else start.astimezone(zone)
        end = end.replace(tzinfo=zone) if end.tzinfo is None else end.astimezone(zone)
    if start >= end:
        raise ValueError("Time start must precede end")
    return {"start": start.isoformat(), "end": end.isoformat(), "timezone": timezone,
            "expression": expression, "end_exclusive": True}


def understand(question, context, requested_at, source, ontology, call_model, available_results=None,
               datasource_ids=None, schemas=None, query_guidance=None, knowledge_context=None):
    active_ids = set(datasource_ids if datasource_ids is not None else [source.get("datasource_id")])
    prompt = (
        f"\nCurrent question: {question}\nPrevious slots: {json.dumps(context, ensure_ascii=False)}"
        f"\nOntology: {json.dumps(ontology, ensure_ascii=False)}"
        f"\nAvailable result references: {json.dumps(available_results or [])}"
        f"\nActive datasource IDs: {json.dumps(sorted(identifier for identifier in active_ids if identifier))}"
        f"\nAvailable schemas for resolving business definitions (no other resources are available): "
        f"{json.dumps(schemas or {}, ensure_ascii=False)}"
        f"\nMatched query guidance (not live evidence or extra permissions): {json.dumps(query_guidance or [], ensure_ascii=False)}"
        f"\nStage knowledge (definitions and guidance, not live observations): {json.dumps(knowledge_context or {}, ensure_ascii=False)}"
    )
    extracted = parse_json(call_model("fast", "generate_response", prompt, request_type="query", node="understanding"))
    if extracted.get("intent") not in ("query", "analysis", "concept", "reject"):
        raise ValueError("Invalid structured intent")
    if type(extracted.get("followup")) is not bool or not isinstance(extracted.get("slots"), dict):
        raise ValueError("NER requires followup flag and slot patches")
    slots = deepcopy(context) if extracted["followup"] else {}
    for slot in slots.values():
        slot["origin"] = "inherited"
    for name, patch in extracted["slots"].items():
        if name not in SLOTS or not isinstance(patch, dict) or "value" not in patch:
            raise ValueError("Invalid NER slot patch")
        span = patch.get("span")
        if (not isinstance(span, list) or len(span) != 2 or any(type(n) is not int for n in span)
                or not 0 <= span[0] < span[1] <= len(question)):
            raise ValueError("NER span is outside the original question")
        slots[name] = {"value": patch["value"], "span": span, "text": question[span[0]:span[1]],
                       "origin": "current"}
    if "time" in slots and slots["time"]["origin"] == "current":
        slots["time"]["value"] = resolve_time(slots["time"]["value"], requested_at,
                                               source.get("timezone", "UTC"), source.get("business_day_start", 0))
        slots["time"]["derived_by"] = "business_calendar_v1"
    clarification = extracted.get("clarification")
    if extracted["followup"] and not context:
        clarification = "No prior confirmed context; specify the entity, metric and time range"
    if clarification is not None and (not isinstance(clarification, str) or not clarification.strip()):
        raise ValueError("Clarification must be a non-empty question")
    for name in ("entities", "metrics", "dimensions"):
        ids = slots.get(name, {}).get("value", [])
        if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
            raise ValueError(f"NER {name} must contain exact ontology IDs")
        if any(item not in ontology.get(name, {}) for item in ids):
            raise ValueError(f"Unknown {name} ID")
    metrics = slots.get("metrics", {}).get("value", [])
    dimensions = set(slots.get("dimensions", {}).get("value", []))
    requires_plan = bool(active_ids) and source.get("datasource_id") not in active_ids
    runtime_metrics = []
    for metric_id in metrics:
        metric = ontology["metrics"][metric_id]
        if "allowed_dimensions" in metric and not dimensions <= set(metric["allowed_dimensions"]):
            clarification = f"Dimensions are incompatible with metric {metric_id}; specify a compatible definition"
        if extracted["intent"] != "concept":
            mappings = metric.get("mappings", {})
            if mappings:
                if not active_ids.intersection(mappings):
                    clarification = f"Metric {metric_id} is not computable on the active datasources; its explicit mapping is outside the active set"
                if source.get("datasource_id") not in mappings:
                    requires_plan = True
            else:
                runtime_metrics.append(metric_id)
                if not any((schemas or {}).get(identifier, {}).get("schema", {}).get("tables")
                           for identifier in active_ids):
                    clarification = f"Metric {metric_id} needs a saved schema in the active Profile to resolve its business definition"
                requires_plan = requires_plan or len(active_ids) > 1
    references = slots.get("result_reference", {}).get("value", [])
    if isinstance(references, list) and len(references) > 1:
        clarification = "Multiple result references; specify exactly one result"
    if available_results is not None:
        if references and (not isinstance(references, list) or set(references) - set(available_results)):
            raise ValueError("Unknown conversation result reference")
        if extracted["followup"] and len(available_results) > 1 and not references:
            clarification = "Multiple previous results; specify exactly one result reference"
    normalized = f"{question}\nConfirmed slot context: {json.dumps(slots, ensure_ascii=False)}"
    return {"intent": extracted["intent"], "slots": slots, "normalized_question": normalized,
            "clarification": clarification, "requested_at": requested_at, "requires_plan": requires_plan,
            "runtime_metrics": runtime_metrics}
