import copy
import re
import time
from typing import Any, Dict, List, Optional

import openai
import requests


class LLMError(RuntimeError):
    pass


def nested_set(data: Dict, path: str, value: Any) -> None:
    keys = path.split(".")
    for key in keys[:-1]:
        data = data.setdefault(key, {})
    data[keys[-1]] = value


def nested_get(data: Dict, path: str) -> Any:
    for key in path.split("."):
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


class LLMClient:
    def __init__(self, config: Dict[str, Any]):
        self.config = config.get("llm_config", config)
        self.provider = self.config.get("provider", "openai")

    def _classify_intent_type(self, prompt: str) -> str:
        match = re.search(r"\[INTENT_TYPE:([^\]]+)\]", prompt)
        if match:
            return match.group(1).strip()
        return "analysis" if any(word in prompt.lower() for word in (
            "分析", "analysis", "复杂", "complex",
        )) else "query"

    def _get_timeout_by_request_type(self, prompt: str) -> float:
        timeout = self.config.get("timeout", {})
        intent = self._classify_intent_type(prompt)
        default = 240 if intent == "analysis" else 70
        if isinstance(timeout, dict):
            timeout = timeout.get(intent, timeout.get("default", default))
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise LLMError("LLM timeout must be a positive number")
        return timeout

    def _model_parameters(self, model: str) -> Dict[str, Any]:
        configured = self.config.get("parameters", {})
        reasoning = model.lower().startswith(("o1", "o3", "o4", "gpt-5"))
        params = {}
        if not reasoning:
            for name in ("temperature", "top_p"):
                if configured.get(name) is not None:
                    params[name] = configured[name]
        if configured.get("max_tokens") is not None:
            key = "max_completion_tokens" if reasoning or model.lower().startswith(
                ("gpt-4o", "gpt-4-turbo")
            ) else "max_tokens"
            params[key] = configured["max_tokens"]
        return params

    def generate_sql(self, prompt: str, request_type: Optional[str] = None,
                     tools: Optional[List[Dict]] = None) -> str:
        timeout_prompt = f"[INTENT_TYPE:{request_type}] {prompt}" if request_type else prompt
        result = self.chat(
            [{"role": "user", "content": prompt}], tools,
            timeout=self._get_timeout_by_request_type(timeout_prompt),
        )
        content = result.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM returned no text")
        return content.strip()

    def generate_response(self, prompt: str, request_type: Optional[str] = None,
                          tools: Optional[List[Dict]] = None) -> str:
        return self.generate_sql(prompt, request_type, tools)

    def generate_response_with_tools(self, messages: List[Dict],
                                     tools: Optional[List[Dict]] = None) -> Dict[str, Any]:
        return self.chat(messages, tools)

    def list_models(self) -> List[str]:
        section = "openai" if self.provider == "openai_sdk" else self.provider
        config = self.config.get(section, {})
        try:
            if section == "azure_openai":
                client = openai.AzureOpenAI(
                    api_key=config.get("api_key"), azure_endpoint=config.get("endpoint"),
                    api_version=config.get("api_version", "2024-02-01"),
                    timeout=30, max_retries=0,
                )
            elif section in ("openai", "custom"):
                base_url = config.get("base_url", "").removesuffix("/chat/completions")
                client = openai.OpenAI(api_key=config.get("api_key"), base_url=base_url or None,
                                       timeout=30, max_retries=0)
            else:
                raise LLMError(f"Unsupported provider: {self.provider}")
            with client:
                return [model.id for model in client.models.list()]
        except openai.OpenAIError as exc:
            raise LLMError("Unable to list models; check provider endpoint and credentials") from exc

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             model: Optional[str] = None, temperature: Optional[float] = None,
             timeout: Optional[float] = None) -> Dict[str, Any]:
        if not messages:
            raise LLMError("At least one message is required")
        section = "openai" if self.provider == "openai_sdk" else self.provider
        if section not in ("openai", "azure_openai", "custom"):
            raise LLMError(f"Unsupported LLM provider: {self.provider}")
        config = self.config.get(section, {})
        model = model or config.get("deployment_name" if section == "azure_openai" else "model")
        if not model:
            raise LLMError("LLM model/deployment is not configured")
        timeout = timeout or self._get_timeout_by_request_type(
            "\n".join(str(message.get("content") or "") for message in messages)
        )
        parameters = self._model_parameters(model)
        if temperature is not None and not model.lower().startswith(("o1", "o3", "o4", "gpt-5")):
            parameters["temperature"] = temperature
        data = {"model": model, "messages": messages, **parameters}
        if tools:
            data.update(tools=tools, tool_choice="auto")

        if self.provider == "openai_sdk":
            try:
                with openai.OpenAI(
                    api_key=config.get("api_key"),
                    base_url=config.get("base_url") or "https://api.openai.com/v1",
                    organization=config.get("organization") or None,
                    timeout=timeout,
                    max_retries=0,
                ) as client:
                    response = client.chat.completions.create(**data)
                message = response.choices[0].message.model_dump(exclude_none=True)
                return self._validate_message(message)
            except openai.OpenAIError as exc:
                raise LLMError("OpenAI SDK request failed; check endpoint and credentials") from exc

        headers = {"Content-Type": "application/json"}
        if section == "azure_openai":
            endpoint = config.get("endpoint", "").rstrip("/")
            if not endpoint:
                raise LLMError("Azure OpenAI endpoint is not configured")
            headers["api-key"] = config.get("api_key", "")
            if endpoint.endswith("/openai/v1"):
                url = f"{endpoint}/chat/completions"
            else:
                url = f"{endpoint}/openai/deployments/{model}/chat/completions"
                url += f"?api-version={config.get('api_version', '2024-02-01')}"
                data.pop("model")
        else:
            base = config.get("api_url") or config.get("base_url", "")
            if not base:
                raise LLMError("LLM endpoint is not configured")
            url = base.rstrip("/")
            if not url.endswith("/chat/completions") and config.get("request_format", "openai") == "openai":
                url += "/chat/completions"
            api_key = config.get("api_key")
            auth = config.get("auth_type", "bearer").lower()
            if api_key and auth == "bearer":
                headers["Authorization"] = f"Bearer {api_key}"
            elif api_key and auth == "api_key":
                headers[config.get("auth_header", "X-API-Key")] = api_key
            if config.get("organization"):
                headers["OpenAI-Organization"] = config["organization"]

        if section == "custom":
            if config.get("request_format", "openai") != "openai":
                if tools or len(messages) != 1:
                    raise LLMError("Custom request templates support single text requests only")
                data = copy.deepcopy(config.get("request_template", {}))
                nested_set(data, config.get("prompt_field", "prompt"), messages[0]["content"])
                for name, path in config.get("param_mapping", {}).items():
                    if name in self.config.get("parameters", {}):
                        nested_set(data, path, self.config["parameters"][name])
            for key, value in config.get("additional_params", {}).items():
                data.setdefault(key, value)

        result = self._post_json(url, headers, data, timeout)
        if section == "custom" and config.get("response_format", "openai") != "openai":
            content = nested_get(result, config.get("response_path", ""))
            return self._validate_message({"content": content})
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise LLMError("LLM response is missing choices")
        return self._validate_message(choices[0].get("message"))

    @staticmethod
    def _validate_message(message: Any) -> Dict[str, Any]:
        if not isinstance(message, dict):
            raise LLMError("LLM response is missing a message")
        content, calls = message.get("content"), message.get("tool_calls")
        if not calls and (not isinstance(content, str) or not content.strip()):
            raise LLMError("LLM returned an empty response")
        return {"content": content, "tool_calls": calls}

    @staticmethod
    def _post_json(url: str, headers: Dict, data: Dict, timeout: float) -> Dict:
        deadline = time.monotonic() + timeout
        for attempt in range(3):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LLMError("LLM request timed out")
            try:
                response = requests.post(url, headers=headers, json=data, timeout=remaining)
            except requests.RequestException as exc:
                raise LLMError("LLM connection failed or timed out") from exc
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    delay = min(2 ** attempt, max(0, deadline - time.monotonic()))
                    time.sleep(delay)
                    continue
            if not response.ok:
                raise LLMError(f"LLM API returned HTTP {response.status_code}")
            try:
                result = response.json()
            except ValueError as exc:
                raise LLMError("LLM API returned invalid JSON") from exc
            if not isinstance(result, dict):
                raise LLMError("LLM API response must be an object")
            return result
        raise LLMError("LLM request exhausted retries")
