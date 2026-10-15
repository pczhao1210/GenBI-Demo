import json
import re
from typing import Any, Dict, List

from utils.config_manager import ConfigManager
from utils.llm_client import LLMClient
from utils.mcp_client import MCPClient, normalize_response
from utils.sql_utils import clean_sql_response, validate_readonly_sql
from utils.datasources import DatabaseAdapter


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
        if step.get("step_type") not in ("sql_query", "external_data", "llm_analysis", "user_input"):
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
            step["dependencies"] = list(dict.fromkeys([*dependencies, *normalized]))
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
        engine = self.config.resolve_datasource(database)["engine"]
        return build_schema_prompt(question, schema["tables"], schema.get("descriptions", {}), engine)

    def generate_sql(self, question: str, database: str) -> str:
        response = self.llm.generate_sql(self.sql_prompt(question, database), request_type="query")
        return validate_readonly_sql(clean_sql_response(response), self.config.resolve_datasource(database)["engine"])

    def query(self, question: str, database: str) -> Dict[str, Any]:
        self.database_config(database)
        sql = self.generate_sql(question, database)
        source = self.config.resolve_datasource(database)
        result = DatabaseAdapter(source, self.mcp).query(sql)
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
        response = self.llm.generate_response(
            "Classify the user request. Reply only query (retrieval, statistics, comparisons), "
            "analysis (explain causes or give recommendations), or reject (modify database data). "
            f"\nUser request: {question}", request_type="query",
        ).strip().lower()
        if response not in ("query", "analysis", "reject"):
            raise ValueError("LLM returned an invalid intent")
        return response

    def analysis_plan(self, question: str, database: str,
                      previous_plan: Dict = None, feedback: str = "") -> Dict[str, Any]:
        prompt = (
            "Return a JSON analysis plan without markdown. Use only the supplied schema. "
            "Step types: sql_query, external_data, llm_analysis. Each step has a unique positive "
            "integer step_id, description, step_type, and dependencies (integer IDs). "
            "SQL steps use query_requirements with tables, filters, metrics and grouping. "
            "Analysis steps use analysis_requirements with method, input_data (integer step IDs), "
            "focus_areas. External steps use data_requirements with a search query. "
            "Do not request unavailable external facts as if they were already known. "
            'Top-level shape: {"analysis_goal": "...", "steps": [...], "expected_output": "..."}\n'
            + self.sql_prompt(question, database)
        )
        if previous_plan is not None:
            prompt += f"\nPrevious plan: {json.dumps(previous_plan, ensure_ascii=False)}\nFeedback: {feedback}"
        response = self.llm.generate_response(prompt, request_type="analysis")
        block = re.search(r"```(?:json)?\s*(.*?)```", response, re.DOTALL | re.IGNORECASE)
        try:
            plan = json.loads(block.group(1) if block else response)
        except (ValueError, TypeError) as exc:
            raise ValueError("LLM returned an invalid JSON analysis plan") from exc
        return validate_plan(plan)

    def execute_plan(self, plan: Dict, question: str, database: str) -> Dict[str, Any]:
        plan = validate_plan(plan)
        self.database_config(database)
        self.schema(database)
        results = {}
        for step in plan["steps"]:
            step_id = step["step_id"]
            failed = [ref for ref in step["dependencies"] if results[ref]["status"] != "success"]
            if failed:
                results[step_id] = {"status": "skipped", "message": f"Dependencies failed: {failed}"}
                continue
            try:
                results[step_id] = self.execute_step(step, question, database, results)
            except (ValueError, RuntimeError) as exc:
                results[step_id] = {"status": "error", "message": str(exc)}
        completed = all(result["status"] == "success" for result in results.values())
        return {"status": "success" if completed else "partial", "plan": plan, "steps": results,
                "completed": completed}

    def execute_step(self, step: Dict, question: str, database: str, results: Dict) -> Dict:
        if step["step_type"] == "sql_query":
            requirement = json.dumps(step.get("query_requirements", {}), ensure_ascii=False)
            result = self.query(f"{question}\nStep: {step.get('description', '')}\n{requirement}", database)
            return {**result, "status": "success"}
        if step["step_type"] == "external_data":
            requirements = step.get("data_requirements", {})
            query = requirements.get("query") or " ".join(
                str(value) for value in requirements.values() if value
            ) or step.get("description")
            if not query:
                raise ValueError("External data step requires a search query")
            payload = result_payload(self.mcp.call_mcp_server(
                "playwright", "search_web", {"query": query, "max_results": 5},
            ))
            if not payload.get("results"):
                raise RuntimeError("No external sources found; no synthetic data substituted")
            return {"status": "success", "data": payload}
        if step["step_type"] == "llm_analysis":
            requirements = step["analysis_requirements"]
            inputs = {ref: results[ref] for ref in requirements["input_data"]}
            prompt = (
                f"Question: {question}\nRequirements: {json.dumps(requirements, ensure_ascii=False)}\n"
                f"Evidence by exact step ID: {json.dumps(inputs, ensure_ascii=False)}\n"
                "Base conclusions only on the supplied evidence. Explicitly report missing data, "
                "truncation, source uncertainty, and limits of causal inference."
            )
            return {"status": "success", "data": self.llm.generate_response(prompt, request_type="analysis")}
        raise ValueError(f"Step requires workflow input: {step['step_type']}")


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
