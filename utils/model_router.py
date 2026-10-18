import threading
import time

from utils.llm_client import LLMClient, TransientLLMError
from utils.tool_catalog import version_of
from utils.model_config import with_model
from utils.prompts import compose_prompt, node_prompt

NODE_ROLES = {
    "understanding": "fast", "intent": "fast", "sql_generation": "sql", "sql_repair": "sql",
    "sql_repair_escalation": "reasoning", "planning": "reasoning", "replanning": "reasoning",
    "extraction": "fast", "analysis": "reasoning", "assessment": "reasoning",
    "explanation": "fast", "presentation": "fast",
}


def validate_workflow_config(settings):
    from utils.resource_scope import resource_visibility, validate_visibility
    if not isinstance(settings, dict) or set(settings) - {"nodes"}:
        raise ValueError("Workflow configuration requires nodes")
    nodes = settings.get("nodes", {})
    if not isinstance(nodes, dict) or set(nodes) - set(NODE_ROLES):
        raise ValueError("Unknown workflow node")
    for node, value in nodes.items():
        if not isinstance(value, dict) or set(value) - {
                "role", "model", "model_name", "prompt", "prompt_template", "examples", "example_mode"}:
            raise ValueError(f"Invalid node configuration: {node}")
        if value.get("role", NODE_ROLES[node]) not in ("fast", "sql", "reasoning"):
            raise ValueError(f"Invalid model role: {node}")
        if not isinstance(value.get("prompt", ""), str) or len(value.get("prompt", "")) > 20000:
            raise ValueError("Node prompt must be text of at most 20000 characters")
        if "model" in value and (not isinstance(value["model"], dict) or not value["model"].get("provider")):
            raise ValueError("Node override requires a complete model configuration")
        if "model_name" in value:
            if "model" in value or not isinstance(value["model_name"], str) or not value["model_name"].strip():
                raise ValueError("Select exactly one node model override")
        template = value.get("prompt_template")
        if template is not None and (not isinstance(template, str) or not template.strip() or len(template) > 20000):
            raise ValueError("Node prompt must be non-empty text of at most 20000 characters")
        if value.get("example_mode", "zero_shot") not in ("zero_shot", "one_shot", "few_shot"):
            raise ValueError("Unknown example mode")
        examples = value.get("examples", [])
        if not isinstance(examples, list):
            raise ValueError("Examples must be a list")
        counts = {}
        for example in examples:
            if not isinstance(example, dict) or set(example) - {"profile_id", "visibility", "input", "output"}:
                raise ValueError("Each example requires Profile, input and output")
            validate_visibility(example, example=True)
            if example.get("profile_id") is not None and not isinstance(example["profile_id"], str):
                raise ValueError("Example Profile ID must be a string or null")
            for field in ("input", "output"):
                if not isinstance(example.get(field), str) or not example[field].strip() or len(example[field]) > 10000:
                    raise ValueError("Example input/output must be non-empty text of at most 10000 characters")
            key = (resource_visibility(example, example=True), example.get("profile_id"))
            counts[key] = counts.get(key, 0) + 1
            if counts[key] > 8:
                raise ValueError("At most 8 examples per node and Profile")
    return settings


def effective_model(config, role, node=None):
    settings = config.load_workflow_config().get("nodes", {}).get(node, {})
    role = settings.get("role", role)
    roles = config.load_model_roles()
    selected = settings.get("model", roles.get(role, config.load_llm_config()))
    if "model_name" in settings:
        selected = with_model(config.load_llm_config(), settings["model_name"])
    elif "model_name" in selected:
        selected = with_model(config.load_llm_config(), selected["model_name"])
    origin = "node_override" if "model" in settings or "model_name" in settings else "role_override" if role in roles else "global_default"
    return role, selected, origin, settings.get("prompt", "")


class ModelRouter:
    def __init__(self, config, injected=None, max_calls=32):
        self.config = config
        self.injected = injected
        self.records = []
        self.max_calls = max_calls
        self.deadline = None
        self._lock = threading.Lock()

    def call(self, role, method, *args, node=None, **kwargs):
        if node is not None and node not in NODE_ROLES:
            raise ValueError(f"Unknown workflow node: {node}")
        for attempt in range(1, 4):
            try:
                return self._call_once(role, method, attempt, *args, node=node, **kwargs)
            except TransientLLMError:
                if attempt == 3:
                    raise

    def _call_once(self, role, method, attempt, *args, node=None, **kwargs):
        if role not in ("fast", "sql", "reasoning"):
            raise ValueError(f"Unknown model role: {role}")
        role, selected, origin, prompt = effective_model(self.config, role, node)
        examples = []
        if node and args:
            composed, examples = compose_prompt(self.config, node, args[0])
            args = (composed, *args[1:])
            prompt, _ = node_prompt(self.config, node)
        elif prompt and args:
            args = (args[0] + "\nAdditional node guidance (preserve the required output contract, "
                    "read-only rules and evidence constraints):\n" + prompt, *args[1:])
        if not selected and self.injected is None:
            raise ValueError(f"Model role is not configured: {role}")
        provider = selected.get("provider", "openai")
        section = selected.get("openai" if provider == "openai_sdk" else provider, {})
        record = {"role": role, "provider": provider, "node": node, "config_source": origin,
                  "model": section.get("model", section.get("deployment_name")),
                  "prompt_version": version_of({"contract": "2", "node": node, "prompt": prompt, "examples": examples}),
                  "example_count": len(examples),
                  "status": "RUNNING", "token_usage": None, "attempt": attempt}
        with self._lock:
            if len(self.records) >= self.max_calls:
                raise RuntimeError("Model call budget exhausted")
            if self.deadline is not None and time.monotonic() >= self.deadline:
                raise RuntimeError("Model active time budget exhausted")
            self.records.append(record)
        started = time.monotonic()
        try:
            result = getattr(self.injected or LLMClient(selected), method)(*args, **kwargs)
            record["status"] = "SUCCEEDED"
            return result
        except Exception as exc:
            record.update(status="FAILED", error=str(exc))
            raise
        finally:
            record["seconds"] = time.monotonic() - started


class ToolBudget:
    def __init__(self, max_calls=64):
        self.max_calls = max_calls
        self.records = []
        self._lock = threading.Lock()

    def call(self, capability, function, *args, _tool_metadata=None, **kwargs):
        record = {"capability": capability, "status": "RUNNING", **(_tool_metadata or {})}
        with self._lock:
            if len(self.records) >= self.max_calls:
                raise RuntimeError("Tool call budget exhausted")
            self.records.append(record)
        started = time.monotonic()
        try:
            result = function(*args, **kwargs)
            record["status"] = "SUCCEEDED"
            return result
        except Exception as exc:
            record.update(status="FAILED", error=str(exc))
            raise
        finally:
            record["seconds"] = time.monotonic() - started
