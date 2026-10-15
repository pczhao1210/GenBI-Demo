import threading
import time

from utils.llm_client import LLMClient


class ModelRouter:
    def __init__(self, config, injected=None, max_calls=32):
        self.config = config
        self.injected = injected
        self.records = []
        self.max_calls = max_calls
        self._lock = threading.Lock()

    def call(self, role, method, *args, **kwargs):
        if role not in ("fast", "sql", "reasoning"):
            raise ValueError(f"Unknown model role: {role}")
        roles = self.config.load_model_roles()
        selected = roles.get(role, self.config.load_llm_config())
        if not selected and self.injected is None:
            raise ValueError(f"Model role is not configured: {role}")
        provider = selected.get("provider", "openai")
        section = selected.get("openai" if provider == "openai_sdk" else provider, {})
        record = {"role": role, "provider": provider,
                  "model": section.get("model", section.get("deployment_name")),
                  "prompt_version": "1", "status": "RUNNING", "token_usage": None}
        with self._lock:
            if len(self.records) >= self.max_calls:
                raise RuntimeError("Model call budget exhausted")
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

    def call(self, capability, function, *args, **kwargs):
        record = {"capability": capability, "status": "RUNNING"}
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
