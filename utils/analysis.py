import json
import re
from copy import deepcopy

from utils.bi_service import validate_plan
from utils.semantics import KnowledgeIndex, parse_json


def validate_methods(library, previous=None):
    if not isinstance(library, dict) or not isinstance(library.get("methods", []), list):
        raise ValueError("Method library requires methods list")
    ids = set()
    old = {item["id"]: item for item in (previous or {}).get("methods", [])}
    transitions = {"draft": {"draft", "validated"}, "validated": {"validated", "published", "draft"},
                   "published": {"published", "deprecated"}, "deprecated": {"deprecated"}}
    for item in library.get("methods", []):
        required = {"id", "title", "description", "preconditions", "required_capabilities", "template", "status", "version"}
        if not isinstance(item, dict) or not required <= item.keys() or item["id"] in ids:
            raise ValueError("Method definition is incomplete or duplicated")
        ids.add(item["id"])
        before = old.get(item["id"], {}).get("status", "draft")
        if item["status"] not in transitions[before]:
            raise ValueError("Methods must move through draft -> validated -> published -> deprecated")
        if not isinstance(item["preconditions"], dict) or not isinstance(item["required_capabilities"], list):
            raise ValueError("Method preconditions and capabilities have invalid shapes")
        if item["status"] in ("validated", "published"):
            validation = item.get("validation", {})
            if (not validation.get("reviewer") or not validation.get("fixture_ids")
                    or validation.get("passed") is not True):
                raise ValueError("Publishing requires reviewed validation and regression fixture IDs")
        validate_plan(item["template"])
    return library


class MethodLibrary:
    def __init__(self, library):
        self.methods = [item for item in library.get("methods", []) if item["status"] == "published"]

    def retrieve(self, question, capabilities, conditions):
        suitable = [item for item in self.methods if set(item["required_capabilities"]) <= set(capabilities)
                    and all(conditions.get(key) == value for key, value in item["preconditions"].items())]
        docs = [{"id": item["id"], "title": item["title"], "text": item["description"],
                 "source": "method-library", "version": str(item["version"]), "scope": "*"} for item in suitable]
        selected = KnowledgeIndex({"documents": docs}).search(question, limit=3)
        return [self._portable(next(item for item in suitable if item["id"] == chunk["id"])) for chunk in selected]

    @staticmethod
    def _portable(item):
        # Cases may retain reproduction materials; the planner only receives portable instructions.
        allowed = ("id", "title", "description", "preconditions", "required_capabilities", "version")
        result = {key: deepcopy(item[key]) for key in allowed}
        result["template"] = {"steps": [
            {key: deepcopy(value) for key, value in step.items()
             if key in {"step_id", "step_type", "description", "dependencies", "analysis_requirements"}}
            for step in item["template"]["steps"]]}
        return result


def evidence_summary(results):
    summary = {}
    for ref, result in results.items():
        data = result.get("data")
        if isinstance(data, dict) and "rows" in data:
            data = {**data, "rows": data["rows"][:30], "summary_rows": min(30, len(data["rows"])),
                    "summary_only": len(data["rows"]) > 30}
        summary[str(ref)] = {**result, "data": data}
    return summary


def evidence_content(value):
    if isinstance(value, dict):
        return {key: evidence_content(item) for key, item in value.items()
                if key not in {"collected_at", "fetched_at", "execution_time", "query_id"}}
    if isinstance(value, list):
        return [evidence_content(item) for item in value]
    return value


def validate_conclusion(package, results):
    required = {"answer_sufficiency", "premise", "claims", "hypotheses", "gaps", "next_plan"}
    if not isinstance(package, dict) or not required <= package.keys():
        raise ValueError("Assessment is missing structured conclusion fields")
    if package["answer_sufficiency"] not in ("SUFFICIENT", "QUALIFIED", "INSUFFICIENT"):
        raise ValueError("Invalid answer sufficiency")
    if package["premise"] not in ("CONFIRMED", "REFUTED", "UNKNOWN"):
        raise ValueError("Invalid premise assessment")
    if not all(isinstance(package[key], list) for key in ("claims", "hypotheses", "gaps")):
        raise ValueError("Assessment claims, hypotheses and gaps must be lists")
    for claim in package["claims"]:
        if not isinstance(claim.get("text"), str) or not isinstance(claim.get("facts"), list):
            raise ValueError("Claim requires text and exact numeric fact bindings")
        refs = claim.get("evidence", [])
        if not refs or any(type(ref) is not int or ref not in results for ref in refs):
            raise ValueError("Claim references unavailable evidence")
        if any(results[ref].get("evidence_class") == "interpretation" for ref in refs):
            raise ValueError("Model interpretation cannot substitute for source evidence")
        for fact in claim["facts"]:
            ref, column, row = fact.get("step_id"), fact.get("column"), fact.get("row")
            if type(ref) is not int or ref not in refs or type(row) is not int or row < 0:
                raise ValueError("Invalid fact coordinates")
            data = results[ref].get("data")
            if (not isinstance(data, dict) or column not in data.get("columns", [])
                    or row >= len(data.get("rows", []))):
                raise ValueError("Fact references unavailable result cell")
            value = data["rows"][row][data["columns"].index(column)]
            if type(value) is not type(fact.get("value")) or value != fact.get("value"):
                raise ValueError("Assessment changed a bound result value")
        allowed = {str(fact["value"]) for fact in claim["facts"]}
        if any(number not in allowed for number in re.findall(r"-?\d+(?:\.\d+)?", claim["text"])):
            raise ValueError("Claim contains an unbound number")
    for hypothesis in package["hypotheses"]:
        if hypothesis.get("status") not in ("UNTESTED", "SUPPORTED", "REFUTED", "INCONCLUSIVE"):
            raise ValueError("Invalid hypothesis status")
        refs = hypothesis.get("evidence", [])
        if any(type(ref) is not int or ref not in results for ref in refs):
            raise ValueError("Hypothesis references unavailable evidence")
        if hypothesis["status"] in ("SUPPORTED", "REFUTED") and not refs:
            raise ValueError("Hypothesis judgment requires evidence")
    if package["premise"] == "REFUTED" and package["next_plan"]:
        raise ValueError("Refuted premise cannot force further attribution")
    if package["next_plan"]:
        package["next_plan"] = validate_plan(package["next_plan"])
    return package


def assess(question, results, ledger, call_model):
    prompt = (
        "Assess evidence, not tool success. Output JSON: "
        '{"answer_sufficiency":"SUFFICIENT|QUALIFIED|INSUFFICIENT",'
        '"premise":"CONFIRMED|REFUTED|UNKNOWN","claims":[{"text":"claim without unbound numbers",'
        '"facts":[{"step_id":1,"column":"exact column","row":0,"value":"exact cell value and JSON type"}],'
        '"evidence":[1]}],"hypotheses":[{"id":"h","status":"UNTESTED|SUPPORTED|REFUTED|INCONCLUSIVE",'
        '"evidence":[1]}],"gaps":["unresolved need"],"next_plan":null}. '
        "A supported hypothesis is NOT causal proof. Verify the phenomenon and comparable definitions first. "
        "If premise is false, stop. Search snippets are discovery, not facts. "
        "Truncated or summarized rows cannot support full-population claims. "
        "Request next_plan only for a specific gap with expected new evidence; use a complete valid DAG. "
        f"\nQuestion: {question}\nLedger: {json.dumps(ledger, ensure_ascii=False)}"
        f"\nEvidence: {json.dumps(evidence_summary(results), ensure_ascii=False)}"
    )
    return validate_conclusion(parse_json(call_model("reasoning", "generate_response", prompt,
                                                   request_type="analysis")), results)


def render_conclusion(package, call_model):
    presentation = parse_json(call_model(
        "fast", "generate_response",
        "Arrange these immutable conclusions for display. Return only JSON "
        '{"claim_order":[0,1],"style":"bullets"}. Do not rewrite facts, claims or references.\n'
        + json.dumps(package, ensure_ascii=False), request_type="query"))
    order = presentation.get("claim_order")
    if (not isinstance(order, list) or any(type(i) is not int for i in order)
            or sorted(order) != list(range(len(package["claims"])))):
        raise ValueError("Presentation must preserve every validated claim exactly once")
    lines = [f"Answer sufficiency: {package['answer_sufficiency']}", f"Premise: {package['premise']}"]
    for index in order:
        claim = package["claims"][index]
        lines.append(f"- {claim['text']} [steps: {', '.join(map(str, claim['evidence']))}]")
        for fact in claim["facts"]:
            lines.append(f"  - {fact['column']}: {fact['value']} [step {fact['step_id']}, row {fact['row']}]")
    lines.extend(f"- Gap: {gap}" for gap in package["gaps"])
    lines.append("Supported hypotheses indicate evidence, not proof of causality.")
    return "\n".join(lines)
