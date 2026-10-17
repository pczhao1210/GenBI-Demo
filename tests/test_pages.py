from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

from tests.helpers import ConfigTestCase, query_response
from tests.test_service_api import plan
from utils.config_manager import PROJECT_ROOT
from utils.bi_service import BIService
from utils.run_service import RunService
from utils.run_store import RunStore
from utils.presentation import csv_export


class PageTests(ConfigTestCase):
    def setUp(self):
        super().setUp()
        self.bi = Mock()
        self.bi.identify_intent.return_value = "query"
        self.bi.understand.side_effect = lambda question, *args: {
            "intent": self.bi.identify_intent.return_value, "slots": {},
            "normalized_question": question, "clarification": None,
        }
        self.bi.assess.return_value = {
            "answer_sufficiency": "QUALIFIED", "premise": "UNKNOWN", "claims": [],
            "hypotheses": [], "gaps": ["limited evidence"], "next_plan": None,
        }
        self.bi.present.return_value = "Validated evidence summary"
        self.bi.execute_step.return_value = {
            "status": "success", "sql": "SELECT 1", "data": query_response()["result"]["data"],
        }
        self.runs = RunService(RunStore(self.config.config_dir / "runs.sqlite3"), self.config,
                               lambda **kw: self.bi)
        self.runs.start = self.runs.execute
        for target, value in (
            ("utils.config_manager.ConfigManager", self.config),
            ("utils.mcp_client.MCPClient", self.mcp),
            ("utils.run_service.get_run_service", self.runs),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def page(self, name):
        if name in ("tools.py", "mcp_management.py"):
            app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=15).run()
            app.switch_page("pages/tools.py").run()
        else:
            app = AppTest.from_file(str(PROJECT_ROOT / "pages" / name), default_timeout=15).run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        return app

    def click(self, app, label):
        next(button for button in app.button if button.label == label).click().run()
        self.assertEqual(len(app.exception), 0, str(app.exception))

    def test_athena_config_save_and_connection_buttons(self):
        self.mcp.call_mcp_server_with_config.return_value = {"result": {"success": True, "tables": []}}
        app = self.page("database_config.py")
        app.selectbox[0].set_value("athena").run()
        self.assertEqual(len(app.exception), 0)
        self.click(app, "🔍 测试连接")
        call = self.mcp.call_mcp_server_with_config.call_args
        self.assertEqual(call.args[0], "athena")
        self.assertEqual(call.args[2]["database"], "athena_test")
        self.click(app, "💾 保存配置")
        self.assertEqual(self.config.resolve_datasource("athena")["config"]["database"], "athena_test")

    def test_schema_switch_isolation_and_persistent_clear(self):
        app = self.page("schema_config.py")
        self.assertIn("mysql_orders", app.session_state["table_fields"])
        app.selectbox[0].set_value("legacy-athena").run()
        self.assertEqual(set(app.session_state["table_fields"]), {"athena_orders"})
        self.click(app, "💾 保存所有表的Schema配置")
        self.assertEqual(set(self.config.load_schema_config()["athena"]["tables"]), {"athena_orders"})
        self.click(app, "🗑️ 清空配置")
        app.run()
        self.assertEqual(dict(app.session_state["table_fields"]), {})
        self.assertEqual(self.config.load_schema_config()["athena"]["tables"], {})
        app.selectbox[0].set_value("legacy-mysql").run()
        self.assertEqual(set(app.session_state["table_fields"]), {"mysql_orders"})

    def test_consecutive_new_connections_do_not_overwrite_saved_source(self):
        app = self.page("database_config.py")
        created = []
        for name in ("first-new-source", "second-new-source"):
            app.selectbox(key="source_connection_mysql").set_value("__new__").run()
            identifier = app.session_state["new_source_mysql"]
            app.text_input(key=f"{identifier}_name").set_value(name).run()
            self.click(app, "💾 保存配置")
            self.assertEqual(app.selectbox(key="source_connection_mysql").value, identifier)
            created.append(identifier)
        self.assertNotEqual(*created)
        sources = self.config.load_datasources()
        self.assertEqual([sources[identifier]["name"] for identifier in created],
                         ["first-new-source", "second-new-source"])
        app.text_input(key=f"{created[1]}_name").set_value("edited second source").run()
        self.click(app, "💾 保存配置")
        self.assertEqual(self.config.load_datasources()[created[0]]["name"], "first-new-source")
        self.assertEqual(self.config.load_datasources()[created[1]]["name"], "edited second source")

    def test_stale_new_source_draft_cannot_reuse_saved_id(self):
        app = self.page("database_config.py")
        app.session_state["new_source_mysql"] = "legacy-mysql"
        app.selectbox(key="source_connection_mysql").set_value("__new__").run()
        self.assertNotEqual(app.session_state["new_source_mysql"], "legacy-mysql")
        self.assertEqual(self.config.resolve_datasource("legacy-mysql")["config"]["database"], "mysql_test")

    def test_schema_edits_survive_reruns(self):
        self.mcp.get_tables.return_value = ["mysql_orders"]
        app = self.page("schema_config.py")
        self.click(app, "刷新Schema")
        next(field for field in app.text_input if "_desc_" in (field.key or "")).set_value("edited comment").run()
        app.run()
        self.assertEqual(app.session_state["table_fields"]["mysql_orders"][0]["comment"], "edited comment")

    def test_chat_query_history_and_source_isolation(self):
        app = self.page("chat.py")
        app.chat_input[0].set_value("show rows").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.dataframe), 1)
        app.run()
        self.assertEqual(len(app.dataframe), 1)
        app.selectbox[0].set_value("legacy-athena").run()
        self.assertEqual(len(app.dataframe), 0)
        app.selectbox[0].set_value("legacy-mysql").run()
        self.assertEqual(len(app.dataframe), 1)

    def test_chat_refresh_does_not_reload_artifacts_or_generate_exports(self):
        app = self.page("chat.py")
        with patch.object(self.runs.store, "artifact", wraps=self.runs.store.artifact) as read, \
                patch.object(self.runs.store, "replay", wraps=self.runs.store.replay) as replay, \
                patch("utils.result_view.csv_export", wraps=csv_export) as csv:
            app.chat_input[0].set_value("show rows").run()
            initial = read.call_count
            app.run()
            app.run()
            self.assertEqual(read.call_count, initial)
            replay.assert_not_called()
            csv.assert_not_called()
            run_id = self.runs.store.history()[0]["run_id"]
            app.button(key=f"prepare_export_{run_id}").click().run()
            self.assertEqual(replay.call_count, 1)

    def test_chat_cancel_and_clear_remove_pending_plan(self):
        self.bi.identify_intent.return_value = "analysis"
        self.bi.analysis_plan.return_value = plan()
        app = self.page("chat.py")
        app.chat_input[0].set_value("why").run()
        self.click(app, "取消计划")
        self.assertFalse(any(button.label == "执行计划" for button in app.button))
        app.chat_input[0].set_value("why again").run()
        self.click(app, "清除历史")
        self.assertFalse(any(button.label == "执行计划" for button in app.button))
        self.assertEqual(len(app.chat_message), 0)

    def test_llm_page_imports_and_supports_sdk_provider(self):
        app = self.page("llm_config.py")
        app.selectbox[0].set_value("openai_sdk").run()
        self.assertEqual(len(app.exception), 0)

    def test_analysis_report_survives_rerun(self):
        self.bi.identify_intent.return_value = "analysis"
        self.bi.analysis_plan.return_value = plan()
        def execute(step, *args):
            if step["step_id"] == 1:
                raise RuntimeError("offline")
            return {"status": "success", "data": "persistent analysis"}
        self.bi.execute_step.side_effect = execute
        app = self.page("chat.py")
        app.chat_input[0].set_value("why").run()
        self.click(app, "执行计划")
        app.run()
        content = "\n".join(element.value for element in app.markdown)
        self.assertIn("persistent analysis", content)
        self.assertIn("offline", "\n".join(element.value for element in app.error))
        self.assertIn("PARTIAL", content)
        self.assertEqual(self.bi.execute_step.call_count, 3)

    def test_api_documentation_calls_prefixed_route(self):
        response = Mock(ok=True)
        response.json.return_value = {"success": True, "sql": "SELECT 1"}
        with patch("requests.get", return_value=response), patch("requests.post", return_value=response) as post:
            app = self.page("api_docs.py")
            self.click(app, "测试连接")
            self.assertEqual(post.call_args.args[0], "http://localhost:8000/api/chat/generate-sql")

    def test_management_disables_calls_in_configuration(self):
        app = self.page("mcp_management.py")
        self.mcp.get_server_info.assert_not_called()
        app.button(key="stop_mysql").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.config.load_mcp_config()["mysql"]["status"], "inactive")

    @patch("utils.tool_management.shutil.which", return_value="/fixture/uvx")
    def test_tools_template_discovery_per_tool_enable_and_trial(self, which):
        app = self.page("tools.py")
        app.text_input(key="server_name_fetch").set_value("fetch_fixture")
        self.click(app, "保存为禁用配置")
        server = self.config.load_mcp_config()["fetch_fixture"]
        self.assertEqual(server["status"], "inactive")
        self.mcp.get_server_info.assert_not_called()
        self.mcp.get_server_info.return_value = {"name": "fetch fixture", "tools": [{
            "name": "fetch", "description": "Fetch a URL",
            "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
            "annotations": {"readOnlyHint": True}}]}
        app.checkbox(key="confirm_probe_fetch_fixture").check().run()
        app.button(key="check_fetch_fixture").click().run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        tool_id = "mcp:fetch_fixture:fetch"
        app.checkbox(key=f"enabled_{tool_id}").check()
        next(button for button in app.button if f"tool_form_{tool_id}" in (button.key or "")).click().run()
        app.button(key="start_fetch_fixture").click().run()
        app.button(key=f"default_{tool_id}_external.fetch").click().run()
        self.assertEqual(self.config.load_tools_config()["default_providers"]["external.fetch"], tool_id)
        self.mcp.call_mcp_server.return_value = {"result": {"content": [{"type": "text", "text": "Fixture source"}]}}
        app.text_area(key=f"trial_arguments_{tool_id}").set_value('{"url":"https://example.com"}')
        app.button(key=f"trial_{tool_id}").click().run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        self.mcp.call_mcp_server.assert_called_once()
        self.assertEqual(self.mcp.get_server_info.call_count, 1)

    def test_management_discovers_unregistered_servers_without_overwriting_config(self):
        previous = self.config.load_mcp_config()
        self.mcp.discover_available_servers.return_value = {
            "new_fixture": {"description": "new fixture"}, "mysql": {"description": "discovered mysql"},
        }
        app = self.page("mcp_management.py")
        self.click(app, "🔄 发现服务器")
        saved = self.config.load_mcp_config()
        self.assertEqual(saved["mysql"], previous["mysql"])
        self.assertEqual(saved["new_fixture"]["args"], ["mcp_servers/new_fixture_server.py"])
        self.assertEqual(saved["new_fixture"]["status"], "inactive")

    def test_standard_mcp_status_check_preserves_capability_routing(self):
        self.config.save_mcp_config({"remote": {
            "protocol": "mcp", "type": "streamable_http", "url": "http://example.invalid/mcp",
            "status": "active", "capabilities": {"price.history": "history"},
        }})
        self.mcp.get_server_info.return_value = {
            "name": "fixture", "protocol": "2025-06-18",
            "tools": [{"name": "history", "inputSchema": {"type": "object"}}],
        }
        app = self.page("mcp_management.py")
        app.checkbox(key="confirm_probe_remote").check().run()
        app.button(key="check_remote").click().run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        self.assertEqual(self.config.load_mcp_config()["remote"]["capabilities"], {"price.history": "history"})
        self.mcp.call_mcp_server.return_value = {"result": {"value": "12.5"}}
        result = BIService(self.config, self.mcp).call_capability("price.history", {"region": "Shanghai"})
        self.assertEqual(result, {"value": "12.5"})
        self.mcp.call_mcp_server.assert_called_once_with("remote", "history", {"region": "Shanghai"})

    def test_home_onboarding_and_english_navigation(self):
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=15).run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        content = "\n".join(element.value for element in app.markdown)
        self.assertIn("不代表真实连接测试通过", "\n".join(element.value for element in app.caption))
        app.selectbox(key="language_selector").set_value("English").run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        self.assertIn("Setup wizard", [element.value for element in app.subheader])

    def test_scenarios_display_explicit_sample_without_live_calls(self):
        app = self.page("scenarios.py")
        self.assertTrue(any("SAMPLE_REPLAY" in warning.value for warning in app.warning))
        self.assertEqual(len(app.dataframe), 2)
        self.bi.execute_step.assert_not_called()

    def test_semantics_page_is_usable_without_database_calls(self):
        app = self.page("semantics.py")
        self.assertEqual(len(app.exception), 0)
        self.mcp.call_mcp_server_with_config.assert_not_called()
