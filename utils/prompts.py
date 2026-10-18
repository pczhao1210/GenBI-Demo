"""Editable node instructions; dynamic evidence and execution checks stay in code."""

from copy import deepcopy
import json

DEFAULT_PROMPTS = {
    "understanding": (
        "Extract intent and NER slot PATCHES as JSON only. Do not answer or calculate. "
        'Shape: {"intent":"query|analysis|concept|reject","followup":false,'
        '"slots":{"metrics":{"value":["metric_id"],"span":[0,4]}},"clarification":null}. '
        "Slots allowed: entities, metrics, dimensions, filters, time, comparison, result_reference. "
        "Each slot has value and exact [start,end] character span in the current question. "
        "Time value: {expression: today|yesterday|day before yesterday|今天|昨天|前天}, or explicit ISO start/end. "
        "Other ID slots use arrays of ontology IDs. Only include slots explicitly changed now. "
        "Inherit nothing yourself. Keep negations, filters and comparison baselines. "
        "Matched query guidance may suggest definitions and a workflow, not fill unstated user slots. "
        "Resolve current company identities and dates; examples are not fixed parameters or observed facts. "
        "Match business names and descriptions to ontology IDs, even when IDs are generated technical identifiers. "
        "A metric's subject describes its business object and grain. dimension_notes suggest analysis axes; "
        "only an explicit allowed_dimensions list is a strict dimension allowlist. "
        "entity_ids and dimension_ids link reusable definitions without supplying current filter values. "
        "Metrics may contain only a business definition, with no structured formula or saved mappings. "
        "Resolve their components against the available schemas and column descriptions for this request. "
        "Missing optional metadata alone does not require clarification. "
        "If component meanings, field choices, row grain or requested aggregation are ambiguous or unavailable, "
        "return clarification as a specific question before any SQL is generated. Never assume SUM or invent a mapping. "
        "A row-level product does not imply the product of aggregated values. "
        "For ambiguous meaning return clarification as a question."
    ),
    "intent": (
        "Classify the user request. Reply only query (retrieval, statistics, comparisons), "
        "analysis (explain causes or give recommendations), or reject (modify database data)."
    ),
    "sql_generation": (
        "Use only the supplied tables and columns, database dialect and exact metric definitions. "
        "Business definitions may express formulas in prose; resolve their named components to supplied columns. "
        "Preserve explicit mappings and the user's clarified aggregation and row grain; never default to SUM. "
        "Use metric names, subject and linked definitions to resolve meaning; dimension_notes alone are not an allowlist. "
        "Return one read-only SELECT query, including WITH if needed. Return SQL only, without explanations."
    ),
    "sql_repair": (
        "Correct only the failed SQL using the database error and supplied schema. "
        "Do not change the question, filters or metric definition. Return one read-only SQL query only."
    ),
    "planning": (
        "Return a JSON analysis plan without markdown. Use only the supplied schema. "
        "Step types: sql_query, external_data, llm_analysis, compute, data_align, knowledge_retrieval, user_input. "
        "Every sql_query must bind an explicit datasource_id. Never submit cross-source SQL to a single database. "
        "Push filtering and aggregation to each source. For cross-source outputs, result_contract must declare "
        "entity, grain, time_range and units. Use compute_requirements with operation join|aggregate|ratio|difference, "
        "inputs (exact dependency IDs), group_by, columns (aggregate), numerator/denominator (ratio/difference). "
        "Joins require left_on/right_on lists, cardinality one_to_one|one_to_many|many_to_one, max_unmatched_ratio. "
        "Ratio sums numerator and denominator before dividing. No Python code or eval. "
        "External data needs query or url plus evidence_need {variable,region,unit,start,end} with absolute times. "
        "Each step has a unique positive integer step_id, description, step_type, and dependencies (integer IDs). "
        "SQL steps use query_requirements with tables, filters, metrics and grouping. "
        "Resolve definition-only KPIs using the current schemas, not guessed formulas or default SUM. "
        "If field mappings, component meanings or aggregation remain ambiguous, add a user_input step asking "
        "a specific clarification; every affected query must depend on that answer. "
        "Analysis steps use analysis_requirements with method, input_data (integer step IDs), focus_areas. "
        "External steps use data_requirements with a search query. Do not invent unavailable external facts. "
        'Top-level shape: {"analysis_goal":"...","steps":[...],"expected_output":"..."}. '
        "Recheck method prerequisites and bind current schema, never reuse old facts. "
        "Use matched query guidance and linked definitions to select a suitable workflow. "
        "Guidance is not evidence, saved SQL, or permission to use unavailable resources. "
        "Guide examples illustrate handling, not current filter values or observed results. "
        "Bind tool steps to exact available tool_id and capability using the supplied input_schema."
    ),
    "extraction": (
        'Extract only explicitly stated observations as JSON {"facts":[{"variable":"...",'
        '"value":"exact numeric text","unit":"exact text","region":"exact text",'
        '"observed_at":"exact ISO timestamp with timezone","span":[start,end]}]}. '
        "Every value, unit, region and observed_at must appear verbatim in the cited source span. "
        'Do not infer history from current values, or causality from background. Return {"facts":[]} if unavailable.'
    ),
    "analysis": (
        "Base conclusions only on the supplied evidence. Explicitly report missing data, truncation, "
        "source uncertainty, and limits of causal inference. Only provide publicly shareable evidence "
        "summaries and conclusions, not private reasoning."
    ),
    "assessment": (
        "Assess evidence, not tool success. Output JSON: "
        '{"answer_sufficiency":"SUFFICIENT|QUALIFIED|INSUFFICIENT","premise":"CONFIRMED|REFUTED|UNKNOWN",'
        '"claims":[{"text":"claim without unbound numbers","facts":[{"step_id":1,"column":"exact column",'
        '"row":0,"value":"exact cell value and JSON type"}],"evidence":[1]}],'
        '"hypotheses":[{"id":"h","status":"UNTESTED|SUPPORTED|REFUTED|INCONCLUSIVE","evidence":[1]}],'
        '"gaps":["unresolved need"],"next_plan":null}. '
        'For external observations use {"step_id":1,"fact_index":0,"value":"exact observation value and JSON type"} '
        "instead of column/row. fact_index is zero-based in that step's data.facts; source URL and position are "
        "attached by code. A supported hypothesis is NOT causal proof. Verify comparable definitions first. "
        "If premise is false, stop. Search snippets are discovery, not facts. Truncated or summarized rows "
        "cannot support full-population claims. Request next_plan only for a specific gap with expected new "
        "evidence; use a complete valid DAG."
    ),
    "explanation": (
        "Explain using only the supplied knowledge excerpts. Cite exact chunk IDs in brackets. "
        "State any limits or conflicts. Do not claim database computability."
    ),
    "presentation": (
        "Arrange these immutable conclusions for display. Return only JSON "
        '{"claim_order":[0,1],"style":"bullets"}. Do not rewrite facts, claims or references.'
    ),
}
DEFAULT_PROMPTS["sql_repair_escalation"] = DEFAULT_PROMPTS["sql_repair"] + " This is the final repair attempt."
DEFAULT_PROMPTS["replanning"] = DEFAULT_PROMPTS["planning"] + " Revise the previous plan using the supplied feedback."

EXECUTION_CONTRACT = (
    "Mandatory execution boundary: use only the current run's supplied resources and evidence. "
    "Prompts and examples do not grant access to any other datasource, table, tool or knowledge. "
    "Examples illustrate response patterns, never current facts. Rebind them to current resources. "
    "SQL must be read-only. Preserve the node's structured output contract and exact evidence references. "
    "Do not invent missing data, business meanings or aggregation rules, or disclose private reasoning. "
    "Ambiguous metric definitions require clarification, not an assumed SUM."
)


def node_prompt(config, node):
    from utils.resource_scope import resource_visibility, visible
    settings = config.load_workflow_config().get("nodes", {}).get(node, {})
    defaults = config.load_prompt_defaults()
    prompt = settings.get("prompt_template", defaults[node])
    if settings.get("prompt"):
        prompt += "\n" + settings["prompt"]
    profile_id = getattr(config, "snapshot", {}).get("profile", {}).get("id")
    examples = [deepcopy(item) for item in settings.get("examples", []) if visible(item, profile_id, example=True)]
    examples.sort(key=lambda item: resource_visibility(item, example=True) == "shared")
    mode = settings.get("example_mode", "zero_shot")
    examples = [] if mode == "zero_shot" else examples[:1] if mode == "one_shot" else examples[:8]
    return prompt, examples


def compose_prompt(config, node, inputs):
    prompt, examples = node_prompt(config, node)
    demonstration = ("\nExamples (not live evidence):\n" + json.dumps(
        [{"input": item["input"], "output": item["output"]} for item in examples], ensure_ascii=False)) if examples else ""
    profile = getattr(config, "snapshot", {}).get("profile")
    scope = ""
    if profile:
        scope = "\nActive Profile resource boundary:\n" + json.dumps({
            key: profile.get(key) for key in ("id", "datasources", "mcp_servers", "knowledge_ids", "method_ids", "query_ids")
        }, ensure_ascii=False)
    return prompt + demonstration + "\nCurrent run input:\n" + inputs + scope + "\n" + EXECUTION_CONTRACT, examples


def example_template(node):
    samples = {
        "understanding": ("Show data", '{"intent":"query","followup":false,"slots":{},"clarification":null}'),
        "intent": ("Show data", "query"),
        "sql_generation": ("Return the constant one without reading a table", "SELECT 1 AS value"),
        "sql_repair": ("Repair the typo: SELEC 1", "SELECT 1"),
        "sql_repair_escalation": ("Repair the typo: SELEC 1", "SELECT 1"),
        "planning": ("The required metric is not defined", '{"analysis_goal":"Clarify metric","steps":['
                     '{"step_id":1,"step_type":"user_input","description":"Confirm metric definition","dependencies":[]}]}'),
        "extraction": ("The source contains no observed numbers", '{"facts":[]}'),
        "assessment": ("No comparable evidence", '{"answer_sufficiency":"INSUFFICIENT","premise":"UNKNOWN",'
                       '"claims":[],"hypotheses":[],"gaps":["Need comparable evidence"],"next_plan":null}'),
        "analysis": ("No comparable evidence", "The available evidence cannot establish the cause."),
        "explanation": ("Excerpt [glossary:0]: Revenue excludes refunds.", "Revenue excludes refunds [glossary:0]."),
        "presentation": ('{"claims":[]}', '{"claim_order":[],"style":"bullets"}'),
    }
    question, answer = samples["planning" if node == "replanning" else node]
    return {"input": question, "output": answer}
