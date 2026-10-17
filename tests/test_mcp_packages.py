"""Opt-in public-network integration; never runs during offline discovery."""

import json
import os
import tempfile
import unittest

from utils.config_manager import ConfigManager
from utils.mcp_client import MCPClient
from utils.model_router import ToolBudget
from utils.tool_execution import ToolInvoker
from utils.tool_management import TEMPLATES, ToolManagement


@unittest.skipUnless(os.environ.get("GENBI_REAL_MCP") == "1", "Requires explicit third-party execution approval")
class PackageIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = ConfigManager(temp.name)
        self.client = MCPClient(self.config, run_scoped=True)
        self.addCleanup(self.client.close)

    def prepare(self, template):
        management = ToolManagement(self.config)
        management.save_server(template, {**TEMPLATES[template], "timeout": 90})
        info = management.discover(template, confirmed=True)
        for name in TEMPLATES[template]["capabilities"].values():
            management.update_tool(f"mcp:{template}:{name}", {"enabled": True})
        management.set_server_enabled(template, True)
        return info, ToolInvoker(self.config, self.client, ToolBudget(max_calls=4))

    def test_pinned_fetch_discovers_and_retrieves_real_public_document(self):
        info, invoker = self.prepare("fetch")
        self.assertIn("fetch", [tool["name"] for tool in info["tools"]])
        url = os.environ.get("GENBI_FETCH_URL", "https://learn.microsoft.com/en-us/windows/python/beginners")
        document = invoker.call("external.fetch", {"url": url, "max_length": 80},
                                "mcp:fetch:fetch")
        self.assertTrue(document["text"])
        self.assertEqual(document["url"], url)
        self.assertFalse(document["complete"], document)
        self.assertTrue(document["collected_at"])

    def test_pinned_sequential_thinking_reuses_session_without_private_output(self):
        info, invoker = self.prepare("sequential_thinking")
        self.assertIn("sequentialthinking", [tool["name"] for tool in info["tools"]])
        for number in (1, 2):
            result = invoker.call("reasoning.sequential_thinking", {
                "thought": "PRIVATE_SENTINEL: choose data sources; no internal reasoning",
                "thoughtNumber": number, "totalThoughts": 2, "nextThoughtNeeded": number < 2,
            }, "mcp:sequential_thinking:sequentialthinking")
            self.assertEqual(result["thoughtNumber"], number)
            self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))
        self.assertEqual(len(self.client._context.sessions), 1)
        self.assertEqual(len(invoker.budget.records), 2)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(invoker.budget.records))
