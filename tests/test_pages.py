from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

from tests.helpers import ConfigTestCase, query_response
from tests.test_service_api import plan
from utils.config_manager import PROJECT_ROOT
from utils.run_service import RunService
from utils.run_store import RunStore


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

    def test_schema_edits_survive_reruns(self):
        self.mcp.get_tables.return_value = ["mysql_orders"]
        app = self.page("schema_config.py")
        self.click(app, "刷新Schema")
        app.text_input[0].set_value("edited comment").run()
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
        app.button(key="stop_mysql").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.config.load_mcp_config()["mysql"]["status"], "inactive")
