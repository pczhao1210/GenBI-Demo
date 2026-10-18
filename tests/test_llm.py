import copy
import unittest
from unittest.mock import MagicMock, Mock, patch

import httpx
import openai
import requests

from utils.llm_client import LLMClient, LLMError, TransientLLMError


def response(status=200, content="SELECT 1"):
    result = Mock(status_code=status, ok=status < 400)
    result.json.return_value = {"choices": [{"message": {"content": content}}]}
    return result


class LLMTests(unittest.TestCase):
    @patch("utils.llm_client.openai.OpenAI")
    def test_model_discovery_uses_connection_without_requiring_selected_model(self, factory):
        config = self.config()
        config["openai"].pop("model")
        config["openai"]["base_url"] += "/chat/completions/"
        config["openai"]["organization"] = "test-organization"
        factory.return_value.models.list.return_value = [Mock(id="fast-model"), Mock(id="strong-model")]
        self.assertEqual(LLMClient(config).list_models(), ["fast-model", "strong-model"])
        self.assertEqual(factory.call_args.kwargs["base_url"], "http://example.invalid/v1")
        self.assertEqual(factory.call_args.kwargs["organization"], "test-organization")
        factory.return_value.chat.completions.create.assert_not_called()

    def config(self, provider="openai"):
        return {"provider": provider, "timeout": {"query": 12, "analysis": 45},
                "parameters": {"temperature": 0.3, "top_p": 0.9, "max_tokens": 100},
                "openai": {"api_key": "test-key", "base_url": "http://example.invalid/v1", "model": "gpt-4o"},
                "custom": {"api_key": "test-custom", "base_url": "http://example.invalid/v1", "model": "local"},
                "azure_openai": {"api_key": "test-azure", "endpoint": "https://example.invalid",
                                 "deployment_name": "deployment", "api_version": "test-version"}}

    @patch("utils.llm_client.requests.post", return_value=response())
    def test_bearer_auth_url_timeout_and_reasoning_parameters(self, post):
        config = self.config()
        config["openai"]["model"] = "gpt-5-mini"
        self.assertEqual(LLMClient(config).generate_sql("question", "analysis"), "SELECT 1")
        self.assertEqual(post.call_args.args[0], "http://example.invalid/v1/chat/completions")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-key")
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("temperature", payload)
        self.assertNotIn("top_p", payload)
        self.assertEqual(payload["max_completion_tokens"], 100)
        self.assertLessEqual(post.call_args.kwargs["timeout"], 45)
        self.assertGreater(post.call_args.kwargs["timeout"], 44)

    @patch("utils.llm_client.requests.post", return_value=response())
    def test_custom_endpoint_with_or_without_completion_suffix(self, post):
        config = self.config("custom")
        for endpoint in ("http://example.invalid/v1", "http://example.invalid/v1/chat/completions"):
            config["custom"]["base_url"] = endpoint
            LLMClient(config).generate_sql("question")
            self.assertEqual(post.call_args.args[0], "http://example.invalid/v1/chat/completions")
            self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-custom")

    @patch("utils.llm_client.requests.post", return_value=response())
    def test_azure_traditional_and_v1_urls(self, post):
        config = self.config("azure_openai")
        LLMClient(config).generate_sql("question")
        self.assertIn("/openai/deployments/deployment/chat/completions?api-version=test-version",
                      post.call_args.args[0])
        self.assertNotIn("model", post.call_args.kwargs["json"])
        config["azure_openai"]["endpoint"] = "https://example.invalid/openai/v1"
        LLMClient(config).generate_sql("question")
        self.assertEqual(post.call_args.args[0], "https://example.invalid/openai/v1/chat/completions")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "deployment")

    def test_http_errors_invalid_json_and_empty_text_are_failures(self):
        broken = response()
        broken.json.side_effect = ValueError("invalid JSON")
        for result in (response(401), broken, response(content=""), response(content=None)):
            with self.subTest(result=result), patch("utils.llm_client.requests.post", return_value=result):
                with self.assertRaises(LLMError):
                    LLMClient(self.config()).generate_sql("question")

    @patch("utils.llm_client.time.sleep")
    def test_transient_failure_retries(self, sleep):
        with patch("utils.llm_client.requests.post", side_effect=[response(429), response(503), response()]) as post:
            self.assertEqual(LLMClient(self.config()).generate_sql("question"), "SELECT 1")
        self.assertEqual(post.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_custom_template_is_not_mutated(self):
        config = self.config("custom")
        config["custom"].update(request_format="template", request_template={"body": {}},
                                prompt_field="body.prompt", response_format="template", response_path="text")
        original = copy.deepcopy(config)
        result = Mock(ok=True, status_code=200)
        result.json.return_value = {"text": "answer"}
        with patch("utils.llm_client.requests.post", return_value=result):
            self.assertEqual(LLMClient(config).generate_response("question"), "answer")
        self.assertEqual(config, original)

    def test_network_errors_are_retryable_but_tls_configuration_errors_are_not(self):
        for error in (requests.Timeout("timeout"), requests.ConnectionError("offline")):
            with self.subTest(error=error), patch("utils.llm_client.requests.post", side_effect=error):
                with self.assertRaises(TransientLLMError):
                    LLMClient(self.config()).generate_response("question")
        with patch("utils.llm_client.requests.post", side_effect=requests.exceptions.SSLError("certificate")):
            with self.assertRaises(LLMError) as error:
                LLMClient(self.config()).generate_response("question")
            self.assertNotIsInstance(error.exception, TransientLLMError)

    @patch("utils.llm_client.openai.OpenAI")
    def test_sdk_timeout_keeps_retryable_error_type(self, factory):
        factory.return_value.__enter__.return_value.chat.completions.create.side_effect = openai.APITimeoutError(
            request=httpx.Request("POST", "https://example.invalid"))
        with self.assertRaises(TransientLLMError):
            LLMClient(self.config("openai_sdk")).generate_response("question")

    @patch("utils.llm_client.openai.OpenAI")
    def test_sdk_dispatch_timeout_and_instance_isolation(self, factory):
        sdk = factory.return_value.__enter__.return_value
        sdk.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(model_dump=Mock(return_value={"content": "SELECT 1"})))
        ]
        client = LLMClient(self.config("openai_sdk"))
        self.assertEqual(client.generate_sql("question"), "SELECT 1")
        self.assertEqual(factory.call_args.kwargs["timeout"], 12)
        self.assertEqual(factory.call_args.kwargs["api_key"], "test-key")
        self.assertEqual(factory.call_args.kwargs["max_retries"], 0)

    @patch("utils.llm_client.requests.post", return_value=response())
    def test_chat_preserves_all_messages(self, post):
        messages = [{"role": "system", "content": "instruction"},
                    {"role": "user", "content": "question"}]
        LLMClient(self.config()).generate_response_with_tools(messages)
        self.assertEqual(post.call_args.kwargs["json"]["messages"], messages)

    def test_default_analysis_timeout_and_unknown_provider(self):
        self.assertEqual(LLMClient({})._get_timeout_by_request_type("analysis"), 240)
        with self.assertRaises(LLMError):
            LLMClient({"provider": "unknown"}).generate_sql("question")
