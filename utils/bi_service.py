import json
import re
from typing import Any, Dict, List

from utils.config_manager import ConfigManager
from utils.llm_client import LLMClient
from utils.mcp_client import MCPClient, normalize_response
from utils.sql_utils import clean_sql_response, validate_readonly_sql
from utils.datasources import DatabaseAdapter
from utils.model_router import ModelRouter, ToolBudget
from utils.semantics import KnowledgeIndex


def result_payload(response: Dict[str, Any]) -> Dict[str, Any]:
    response = normalize_response(response)
    if "error" in response:
        raise RuntimeError(response["error"])
    return response["result"]


def build_schema_prompt(question: str, tables: Dict, descriptions: Dict,
                        database: str = "mysql") -> str:
    schema = {}
    for table, info in tables.items():
        columns = info.get("columns", []) if isinstance(info, dict) else info
        if not isinstance(columns, list):
            raise ValueError(f"Invalid columns for table {table}")
        schema[table] = {"description": descriptions.get(table, ""), "columns": columns}
    return (f"Database dialect: {database}\nQuestion: {question}\n"
            f"Schema:\n{json.dumps(schema, ensure_ascii=False)}\n"
            "Use only the supplied tables and columns. Return one read-only SELECT query, "
            "including WITH if needed. Return SQL only, without explanations.")


def validate_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(plan, dict) or not isinstance(plan.get("steps"), list) or not plan["steps"]:
        raise ValueError("Analysis plan must contain a non-empty steps list")
    steps, identifiers = [], set()
    for raw in plan["steps"]:
        if not isinstance(raw, dict):
            raise ValueError("Each analysis step must be an object")
        step = dict(raw)
        step_id = step.get("step_id")
        if type(step_id) is not int or step_id <= 0 or step_id in identifiers:
            raise ValueError("Analysis step IDs must be unique positive integers")
        if step.get("step_type") not in ("sql_query", "external_data", "llm_analysis", "user_input",
                                         "compute", "data_align", "knowledge_retrieval"):
            raise ValueError(f"Unsupported analysis step type: {step.get('step_type')}")
        dependencies = step.get("dependencies", [])
        if not isinstance(dependencies, list) or any(type(ref) is not int for ref in dependencies):
            raise ValueError("Dependencies must be integer step IDs")
        step["dependencies"] = list(dict.fromkeys(dependencies))
        optional = step.get("optional_dependencies", [])
        if (not isinstance(optional, list) or any(type(ref) is not int for ref in optional)
                or set(optional) & set(dependencies)):
            raise ValueError("Optional dependencies must be distinct integer step IDs")
        if optional and not step.get("allow_missing_inputs"):
            raise ValueError("Optional dependencies require allow_missing_inputs")
        step["optional_dependencies"] = list(dict.fromkeys(optional))
        if step["step_type"] == "llm_analysis":
            requirements = dict(step.get("analysis_requirements", {}))
            refs = requirements.get("input_data", dependencies)
            if not isinstance(refs, list):
                raise ValueError("input_data must be a list of step IDs")
            normalized = []
            for ref in refs:
                if isinstance(ref, str):
                    match = re.fullmatch(r"(?:步骤|step)\s*(\d+)", ref, re.IGNORECASE)
                    ref = int(match.group(1)) if match else ref
                if type(ref) is not int:
                    raise ValueError("input_data must use exact step IDs, not descriptions")
                normalized.append(ref)
            if not normalized:
                raise ValueError("Analysis requires at least one data input")
            requirements["input_data"] = normalized
            step["analysis_requirements"] = requirements
            step["dependencies"] = list(dict.fromkeys([*dependencies, *(ref for ref in normalized if ref not in optional)]))
        if step["step_type"] in ("compute", "data_align"):
            inputs = step.get("compute_requirements", {}).get("inputs")
            if (not isinstance(inputs, list) or not inputs or any(type(ref) is not int for ref in inputs)
                    or not set(inputs) <= set(dependencies + optional)):
                raise ValueError("Compute inputs must be declared step dependencies")
        identifiers.add(step_id)
        steps.append(step)
    for step in steps:
        if any(ref not in identifiers for ref in step["dependencies"] + step["optional_dependencies"]):
            raise ValueError("Analysis plan references an unknown step")
    ordered, completed = [], set()
    pending = steps[:]
    while pending:
        ready = [step for step in pending
                 if set(step["dependencies"] + step["optional_dependencies"]) <= completed]
        if not ready:
            raise ValueError("Analysis plan contains a dependency cycle")
        for step in sorted(ready, key=lambda item: item["step_id"]):
            ordered.append(step)
            completed.add(step["step_id"])
            pending.remove(step)
    return {**plan, "steps": ordered}


class BIService:
    def __init__(self, config_manager=None, mcp_client=None, llm_client=None):
        self.config = config_manager or ConfigManager()
        self.mcp = mcp_client or MCPClient(self.config)
        self._llm = llm_client
        self.router = ModelRouter(self.config, llm_client)
        self.tools = ToolBudget()

    @property
    def llm(self):
        if self._llm is None:
            config = self.config.load_llm_config()
            if not config:
                raise ValueError("LLM is not configured")
            self._llm = LLMClient(config)
        return self._llm

    def schema(self, database: str) -> Dict[str, Any]:
        schema = self.config.resolve_datasource(database)["schema"]
        if not schema.get("tables"):
            raise ValueError(f"No schema configured for {database}")
        return schema

    def database_config(self, database: str) -> Dict[str, Any]:
        config = self.config.resolve_datasource(database)["config"]
        if not config:
            raise ValueError(f"No connection configured for {database}")
        return config

    def sql_prompt(self, question: str, database: str) -> str:
        schema = self.schema(database)
        source = self.config.resolve_datasource(database)
        prompt = build_schema_prompt(question, schema["tables"], schema.get("descriptions", {}), source["engine"])
        bindings = {identifier: definition for identifier, definition in self.config.load_semantics().get("metrics", {}).items()
                    if identifier in question and source["datasource_id"] in definition["mappings"]}
        if bindings:
            prompt += "\nUse these exact metric definitions, filters and source mappings:\n" + json.dumps(
                bindings, ensure_ascii=False)
        return prompt

    def generate_sql(self, question: str, database: str) -> str:
        response = self.router.call("sql", "generate_sql", self.sql_prompt(question, database), request_type="query")
        return validate_readonly_sql(clean_sql_response(response), self.config.resolve_datasource(database)["engine"])

    def query(self, question: str, database: str) -> Dict[str, Any]:
        self.database_config(database)
        sql = self.generate_sql(question, database)
        source = self.config.resolve_datasource(database)
        for correction in range(3):
            try:
                result = self.tools.call("database.query", DatabaseAdapter(source, self.mcp).query, sql)
                break
            except RuntimeError as exc:
                if correction == 2 or not re.search(
                        r"syntax|unknown column|invalid column|column .*does not exist|invalid identifier",
                        str(exc), re.IGNORECASE):
                    raise
                prompt = (self.sql_prompt(question, database) + f"\nFailed SQL: {sql}\nDatabase error: {exc}"
                          "\nCorrect only this query without changing the question, filters or metric definition.")
                response = self.router.call("sql" if correction == 0 else "reasoning", "generate_sql",
                                            prompt, request_type="query")
                sql = validate_readonly_sql(response, source["engine"])
        data = result.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Query response is missing data")
        columns, rows = data.get("columns"), data.get("rows")
        if (not isinstance(columns, list) or not all(isinstance(column, str) for column in columns)
                or not isinstance(rows, list)
                or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)):
            raise RuntimeError("Query response has invalid columns or rows")
        return {"intent": "query", "question": question, "database": database,
                "sql": sql, "status": "success", **result}

    def identify_intent(self, question: str) -> str:
        response = self.router.call("fast", "generate_response",
            "Classify the user request. Reply only query (retrieval, statistics, comparisons), "
            "analysis (explain causes or give recommendations), or reject (modify database data). "
            f"\nUser request: {question}", request_type="query",
        ).strip().lower()
        if response not in ("query", "analysis", "reject"):
            raise ValueError("LLM returned an invalid intent")
        return response

    def analysis_plan(self, question: str, database: str,
                      previous_plan: Dict = None, feedback: str = "", datasource_ids=None) -> Dict[str, Any]:
        from utils.analysis import MethodLibrary
        selected_metrics = [definition for identifier, definition in self.config.load_semantics().get("metrics", {}).items()
                            if identifier in question]
        conditions = {"has_components": any(m.get("numerator") and m.get("denominator") for m in selected_metrics),
                      "has_time": '"time"' in question}
        methods = MethodLibrary(self.config.load_methods()).retrieve(
            question, ["database.query", "knowledge.search", "external.search", "llm.analysis"], conditions)
        prompt = (
            "Return a JSON analysis plan without markdown. Use only the supplied schema. "
            "Step types: sql_query, external_data, llm_analysis, compute, data_align, knowledge_retrieval, user_input. "
            "Every sql_query must bind an explicit datasource_id. Never submit cross-source SQL to a single database. "
            "Push filtering and aggregation to each source. For cross-source outputs, result_contract must declare "
            "entity, grain, time_range and units. Use compute_requirements with operation join|aggregate|ratio|difference, "
            "inputs (exact dependency IDs), group_by, columns (aggregate), numerator/denominator (ratio/difference). "
            "Joins require left_on/right_on lists, cardinality one_to_one|one_to_many|many_to_one, max_unmatched_ratio. "
            "Ratio sums numerator and denominator before dividing. No Python code or eval. "
            "External data needs query or url plus evidence_need {variable,region,unit,start,end} with absolute times. "
            "Each step has a unique positive "
            "integer step_id, description, step_type, and dependencies (integer IDs). "
            "SQL steps use query_requirements with tables, filters, metrics and grouping. "
            "Analysis steps use analysis_requirements with method, input_data (integer step IDs), "
            "focus_areas. External steps use data_requirements with a search query. "
            "Do not request unavailable external facts as if they were already known. "
            'Top-level shape: {"analysis_goal": "...", "steps": [...], "expected_output": "..."}\n'
            + "\n".join(f"datasource_id: {identifier}\n{self.sql_prompt(question, identifier)}"
                        for identifier in datasource_ids or [database])
            + "\nPortable methods (recheck prerequisites; bind current schema, never reuse old facts): "
            + json.dumps(methods, ensure_ascii=False)
        )
        if previous_plan is not None:
            prompt += f"\nPrevious plan: {json.dumps(previous_plan, ensure_ascii=False)}\nFeedback: {feedback}"
        response = self.router.call("reasoning", "generate_response", prompt, request_type="analysis")
        block = re.search(r"```(?:json)?\s*(.*?)```", response, re.DOTALL | re.IGNORECASE)
        try:
            plan = json.loads(block.group(1) if block else response)
        except (ValueError, TypeError) as exc:
            raise ValueError("LLM returned an invalid JSON analysis plan") from exc
        return validate_plan(plan)

    def assess(self, question, results, ledger):
        from utils.analysis import assess
        return assess(question, results, ledger, self.router.call)

    def present(self, conclusion):
        from utils.analysis import render_conclusion
        return render_conclusion(conclusion, self.router.call)

    def execute_plan(self, plan: Dict, question: str, database: str) -> Dict[str, Any]:
        plan = validate_plan(plan)
        for step in plan["steps"]:
            if step["step_type"] == "sql_query":
                self.database_config(step.get("datasource_id", database))
                self.schema(step.get("datasource_id", database))
        results = {}
        for step in plan["steps"]:
            step_id = step["step_id"]
            failed = [ref for ref in step["dependencies"] if results[ref]["status"] != "success"]
            if failed:
                results[step_id] = {"status": "skipped", "message": f"Dependencies failed: {failed}"}
                continue
            try:
                results[step_id] = self.execute_step(step, question, step.get("datasource_id", database), results)
            except (ValueError, RuntimeError) as exc:
                results[step_id] = {"status": "error", "message": str(exc)}
        completed = all(result["status"] == "success" for result in results.values())
        return {"status": "success" if completed else "partial", "plan": plan, "steps": results,
                "completed": completed}

    def execute_step(self, step: Dict, question: str, database: str, results: Dict) -> Dict:
        if step["step_type"] == "sql_query":
            requirement = json.dumps(step.get("query_requirements", {}), ensure_ascii=False)
            result = self.query(f"{question}\nStep: {step.get('description', '')}\n{requirement}", database)
            contract = step.get("result_contract", {})
            if contract:
                allowed = {"entity", "grain", "time_range", "units"}
                if set(contract) - allowed:
                    raise ValueError("Unsupported result alignment contract fields")
                if not isinstance(contract.get("units", {}), dict) or set(contract.get("units", {})) - set(result["data"]["columns"]):
                    raise ValueError("Result contract units reference unavailable columns")
                result["data"].update(contract)
                result["data"]["warnings"].append("Semantic alignment contract was declared in the approved plan.")
            return {**result, "status": "success"}
        if step["step_type"] in ("compute", "data_align"):
            from utils.computation import compute
            return compute(step["compute_requirements"], results)
        if step["step_type"] == "knowledge_retrieval":
            chunks = KnowledgeIndex(self.config.load_knowledge()).search(
                step.get("query", step.get("description", question)))
            return {"status": "success", "evidence_class": "knowledge", "data": {"chunks": chunks}}
        if step["step_type"] == "external_data":
            requirements = step.get("data_requirements", {})
            from utils.external_evidence import extract_evidence, extract_structured, fetch_document
            from utils.run_store import utcnow
            need = requirements.get("evidence_need")
            if requirements.get("capability"):
                payload = self.call_capability(requirements["capability"], requirements.get("arguments", {}))
                if need and requirements.get("field_mapping"):
                    document = {"url": f"tool:{requirements['capability']}", "text": json.dumps(payload, ensure_ascii=False),
                                "complete": True, "collected_at": utcnow(), "published_at": None}
                    data = extract_structured(document, need, requirements["field_mapping"])
                    return {"status": "success", "evidence_class": "observation" if data["facts"] else "discovery", "data": data}
                return {"status": "success", "evidence_class": "discovery", "data": payload}
            if requirements.get("url"):
                document = self.tools.call("external.fetch", fetch_document, requirements["url"])
                if not need:
                    return {"status": "success", "evidence_class": "discovery", "data": {"sources": [document], "facts": []}}
                data = (extract_structured(document, need, requirements["field_mapping"])
                        if requirements.get("field_mapping") else extract_evidence(document, need, self.router.call))
                return {"status": "success", "evidence_class": "observation" if data["facts"] else "discovery",
                        "data": data}
            query = requirements.get("query") or " ".join(
                str(value) for value in requirements.values() if value
            ) or step.get("description")
            if not query:
                raise ValueError("External data step requires a search query")
            payload = result_payload(self.tools.call("external.search", self.mcp.call_mcp_server,
                                                     "playwright", "search_web", {"query": query, "max_results": 5}))
            if not payload.get("results"):
                raise RuntimeError("No external sources found; no synthetic data substituted")
            if not need:
                return {"status": "success", "evidence_class": "discovery", "data": payload}
            data = {"sources": [], "facts": [], "warnings": []}
            for candidate in payload["results"][:3]:
                if not candidate.get("url"):
                    data["warnings"].append("Search result has no retrievable URL")
                    continue
                try:
                    document = self.tools.call("external.fetch", fetch_document, candidate["url"])
                    evidence = extract_evidence(document, need, self.router.call)
                    for key in data:
                        data[key].extend(evidence[key])
                except RuntimeError as exc:
                    data["warnings"].append(str(exc))
            if not data["sources"]:
                raise RuntimeError("No source body retrieved: " + "; ".join(data["warnings"]))
            return {"status": "success", "evidence_class": "observation" if data["facts"] else "discovery", "data": data}
        if step["step_type"] == "llm_analysis":
            requirements = step["analysis_requirements"]
            inputs = {ref: results[ref] for ref in requirements["input_data"]}
            prompt = (
                f"Question: {question}\nRequirements: {json.dumps(requirements, ensure_ascii=False)}\n"
                f"Evidence by exact step ID: {json.dumps(inputs, ensure_ascii=False)}\n"
                "Base conclusions only on the supplied evidence. Explicitly report missing data, "
                "truncation, source uncertainty, and limits of causal inference."
            )
            return {"status": "success", "evidence_class": "interpretation",
                    "data": self.router.call("reasoning", "generate_response", prompt, request_type="analysis")}
        raise ValueError(f"Step requires workflow input: {step['step_type']}")

    def understand(self, question, database, context, requested_at):
        from utils.understanding import understand
        sources = self.config.load_datasources()
        matches = [s for s in sources.values() if s["engine"] == database]
        source = sources.get(database) or (matches[0] if len(matches) == 1 else {"timezone": "UTC"})
        return understand(question, context, requested_at, source, self.config.load_semantics(), self.router.call)

    def explain(self, question):
        knowledge = self.config.load_knowledge()
        docs = list(knowledge.get("documents", []))
        for kind in ("entities", "metrics", "dimensions"):
            for identifier, definition in self.config.load_semantics().get(kind, {}).items():
                docs.append({"id": f"ontology-{identifier}", "title": identifier,
                             "text": json.dumps(definition, ensure_ascii=False), "source": "ontology",
                             "version": str(self.config.load_semantics().get("version", 1)), "scope": "*"})
        chunks = KnowledgeIndex({"documents": docs}).search(question)
        if not chunks:
            return {"status": "success", "data": "No relevant knowledge sources found.",
                    "answer_sufficiency": "INSUFFICIENT", "citations": []}
        prompt = ("Explain using only the following knowledge excerpts. Cite exact chunk IDs in brackets. "
                  "State any limits or conflicts. Do not claim database computability."
                  f"\nQuestion: {question}\n{json.dumps(chunks, ensure_ascii=False)}")
        text = self.router.call("fast", "generate_response", prompt, request_type="query")
        return {"status": "success", "data": text, "citations": chunks, "answer_sufficiency": "QUALIFIED"}

    def call_capability(self, capability, arguments):
        matches = [(name, settings["capabilities"][capability])
                   for name, settings in self.config.load_mcp_config().items()
                   if settings.get("status") == "active" and isinstance(settings.get("capabilities"), dict)
                   and capability in settings["capabilities"]]
        if len(matches) != 1:
            raise ValueError(f"Tool capability {capability} requires one explicit active provider, found {len(matches)}")
        server, tool = matches[0]
        return result_payload(self.tools.call(capability, self.mcp.call_mcp_server, server, tool, arguments))


def format_analysis_report(question: str, execution: Dict) -> str:
    successes = sum(step["status"] == "success" for step in execution["steps"].values())
    lines = [f"## {question}", f"Status: {execution['status']} ({successes}/{len(execution['steps'])})"]
    for step in execution["plan"]["steps"]:
        result = execution["steps"][step["step_id"]]
        lines.append(f"\n### {step['step_id']}. {step.get('description', step['step_type'])}")
        lines.append(f"Status: {result['status']}")
        if result.get("message"):
            lines.append(result["message"])
        if result.get("sql"):
            lines.append(f"```sql\n{result['sql']}\n```")
        if result.get("warning"):
            lines.append(result["warning"])
        if isinstance(result.get("data"), str):
            lines.append(result["data"])
        elif result.get("data") is not None:
            lines.append(f"```json\n{json.dumps(result['data'], ensure_ascii=False, indent=2)}\n```")
    return "\n\n".join(lines)
