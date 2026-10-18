from unittest.mock import Mock, patch
import json

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

    def knowledge_template(self, app, kind):
        from utils.knowledge_center import FAMILIES
        app.radio(key="knowledge_entry").set_value("__new__").run()
        family = FAMILIES[kind]
        app.radio(key="knowledge_template").set_value(family).run()
        if family != "references":
            app.selectbox(key=f"knowledge_kind_{family}").set_value(kind).run()
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
        next(box for box in app.checkbox if (box.key or "").endswith("_clear_confirm")).check().run()
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
        app.selectbox(key="primary_source").set_value("legacy-athena").run()
        self.assertEqual(len(app.dataframe), 0)
        app.selectbox(key="primary_source").set_value("legacy-mysql").run()
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
        app.toggle(key=f"enabled_{tool_id}").set_value(True).run()
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

    def test_home_requires_default_model_not_only_saved_connection(self):
        saved = self.config.load_llm_config()
        connection = {**saved, "openai": {**saved["openai"], "model": ""}}
        self.config.save_llm_config(connection)
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=15).run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        self.assertIn("模型与 Prompt — 待配置", "\n".join(item.value for item in app.markdown))
        self.config.save_llm_config(saved)
        app.run()
        self.assertIn("模型与 Prompt — 已配置", "\n".join(item.value for item in app.markdown))

    def test_scenarios_display_explicit_sample_without_live_calls(self):
        app = self.page("scenarios.py")
        self.assertTrue(any("SAMPLE_REPLAY" in warning.value for warning in app.warning))
        self.assertEqual(len(app.dataframe), 2)
        self.bi.execute_step.assert_not_called()

    def test_semantics_page_is_usable_without_database_calls(self):
        app = self.page("semantics.py")
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "业务知识中心")
        self.mcp.call_mcp_server_with_config.assert_not_called()

    def test_chat_title_has_no_duplicate_emoji(self):
        app = self.page("chat.py")
        self.assertEqual(app.title[0].value, "智能聊天")

    def test_profile_editor_persists_multiple_connections_tables_and_edits_same_id(self):
        app = self.page("profiles.py")
        prefix = "profile___new__"
        app.text_input(key=f"{prefix}_name").set_value("Sales")
        app.multiselect(key=f"{prefix}_sources").set_value(["legacy-mysql", "legacy-athena"]).run()
        app.multiselect(key=f"{prefix}_tables_legacy-mysql").set_value(["mysql_orders"])
        app.multiselect(key=f"{prefix}_tables_legacy-athena").set_value(["athena_orders"])
        self.click(app, "保存 Profile")
        profiles = self.config.load_profiles()
        self.assertEqual(len(profiles), 1)
        identifier = next(iter(profiles))
        self.assertEqual(profiles[identifier]["datasources"],
                         {"legacy-mysql": ["mysql_orders"], "legacy-athena": ["athena_orders"]})
        app.text_input(key=f"profile_{identifier}_name").set_value("Updated sales")
        self.click(app, "保存 Profile")
        self.assertEqual(len(self.config.load_profiles()), 1)
        self.assertEqual(self.config.load_profiles()[identifier]["name"], "Updated sales")

    def test_chat_profile_switch_does_not_reuse_another_business_conversation(self):
        from tests.test_profiles import profile
        for name in ("sales", "finance"):
            self.config.save_profile(profile(name))
        app = self.page("chat.py")
        app.selectbox(key="chat_profile").set_value("sales").run()
        app.chat_input[0].set_value("Sales rows").run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        self.assertEqual(self.runs.store.history()[0]["profile_id"], "sales")
        app.selectbox(key="chat_profile").set_value("finance").run()
        self.assertEqual(len(app.chat_message), 0)
        app.selectbox(key="chat_profile").set_value("sales").run()
        self.assertEqual(len(app.dataframe), 1)
        self.config.delete_profile("sales")
        app.run()
        self.assertEqual(app.selectbox(key="chat_profile").value, "sales")
        self.assertEqual(len(app.chat_input), 0)
        self.assertTrue(app.error)
        app.selectbox(key="chat_profile").set_value("finance").run()
        self.assertEqual(len(app.exception), 0)

    def test_model_provider_switch_renders_fields_before_saving(self):
        app = self.page("llm_config.py")
        app.selectbox(key="global_provider").set_value("azure_openai").run()
        self.assertTrue(any(field.key == "global_azure_openai_endpoint" for field in app.text_input))
        self.assertFalse(any(field.key == "global_openai_base_url" for field in app.text_input))
        self.assertEqual(self.config.load_llm_config()["provider"], "openai")

    def test_kpi_form_creates_and_edits_definition_without_json(self):
        app = self.page("semantics.py")
        prefix = "metrics___new__"
        app.text_input(key=f"{prefix}_name").set_value("Order count")
        app.text_input(key=f"{prefix}_id").set_value("orders")
        app.text_area(key=f"{prefix}_description").set_value("Paid order count")
        app.text_input(key=f"{prefix}_formula").set_value("COUNT(*)")
        app.text_input(key=f"{prefix}_unit").set_value("orders")
        app.text_input(key=f"{prefix}_time").set_value("updated_at")
        app.multiselect(key=f"{prefix}_sources").set_value(["legacy-mysql"]).run()
        app.multiselect(key=f"{prefix}_legacy-mysql_mysql_orders_columns").set_value(["updated_at"])
        self.click(app, "保存业务定义")
        definition = self.config.load_semantics()["metrics"]["orders"]
        self.assertEqual(definition["mappings"]["legacy-mysql"]["table"], "mysql_orders")
        self.assertEqual(definition["formula"], "COUNT(*)")
        app.text_area(key="metrics_orders_description").set_value("Updated definition")
        self.click(app, "保存业务定义")
        self.assertEqual(self.config.load_semantics()["metrics"]["orders"]["description"], "Updated definition")
        self.assertEqual(len(self.config.load_semantics()["metrics"]), 1)

    def test_definition_forms_generate_stable_ids_without_technical_defaults(self):
        app = self.page("semantics.py")
        self.assertEqual(len(app.tabs), 0)
        self.assertEqual(len(app.radio(key="knowledge_template").options), 3)
        for kind, definition in (
            ("metrics", "KPI1 = A * B * C; A is unit price, B is quantity, C is discount factor."),
            ("entities", "An order is a purchase made by a customer."),
            ("dimensions", "Region is the customer's delivery region."),
        ):
            with self.subTest(kind=kind):
                self.knowledge_template(app, kind)
                app.text_input(key=f"{kind}___new___name").set_value(kind)
                app.text_area(key=f"{kind}___new___description").set_value(definition)
                app.button(key=f"{kind}___new___save").click().run()
                self.assertEqual(len(app.exception), 0, str(app.exception))
                items = self.config.load_semantics()[kind]
                identifier = next(iter(items))
                self.assertEqual(items[identifier]["description"], definition)
                self.assertEqual(items[identifier]["name"], kind)
                self.assertEqual(items[identifier]["visibility"], "shared")
                for field in ("aggregation", "formula", "allowed_dimensions", "mappings"):
                    self.assertNotIn(field, items[identifier])
                app.text_area(key=f"{kind}_{identifier}_description").set_value(definition + " Updated.")
                app.button(key=f"{kind}_{identifier}_save").click().run()
                self.assertEqual(list(self.config.load_semantics()[kind]), [identifier])
        self.assertNotIn("aggregation", next(iter(self.config.load_semantics()["metrics"].values())))

    def test_manual_semantic_id_cannot_overwrite_existing_definition(self):
        self.config.save_semantics({"metrics": {"orders": {"description": "Original definition"}}})
        app = self.page("semantics.py")
        app.text_input(key="metrics___new___id").set_value("orders")
        app.text_input(key="metrics___new___name").set_value("Replacement name")
        app.text_area(key="metrics___new___description").set_value("Replacement")
        app.button(key="metrics___new___save").click().run()
        self.assertTrue(app.error)
        self.assertEqual(self.config.load_semantics()["metrics"]["orders"]["description"], "Original definition")

    def test_knowledge_requires_only_title_and_body(self):
        app = self.page("semantics.py")
        self.knowledge_template(app, "documents")
        app.text_input(key="doc___new___title").set_value("Business definitions")
        app.text_area(key="doc___new___text").set_value("Revenue excludes refunds.")
        self.click(app, "保存知识文档")
        doc = self.config.load_knowledge()["documents"][0]
        self.assertEqual(doc["source"], f"manual:{doc['id']}")
        self.assertEqual(doc["version"], "1")
        self.assertEqual(doc["scope"], "*")
        self.assertEqual(doc["text"], "Revenue excludes refunds.")

    def test_method_and_case_drafts_need_no_steps_or_review_metadata(self):
        app = self.page("semantics.py")
        self.knowledge_template(app, "methods")
        app.text_input(key="method___new___title").set_value("Compare line revenue")
        app.text_area(key="method___new___description").set_value("Compare the same KPI across periods.")
        self.click(app, "保存分析方法")
        method = self.config.load_methods()["methods"][0]
        self.assertEqual(method["template"]["steps"], [])
        self.assertEqual(method["status"], "draft")
        prefix = f"case_{method['id']}___new__"
        app.text_area(key=f"{prefix}_problem_structure").set_value("Why did revenue decrease?")
        app.text_area(key=f"{prefix}_adaptation").set_value("Compare periods with the same definition.")
        self.click(app, "保存相似问题")
        case = self.config.load_methods()["methods"][0]["cases"][0]
        self.assertEqual(case["status"], "draft")
        self.assertEqual(case["validation"]["reviewer"], "")

    def test_knowledge_form_saves_updates_and_searches_document(self):
        app = self.page("semantics.py")
        self.knowledge_template(app, "documents")
        prefix = "doc___new__"
        app.text_input(key=f"{prefix}_title").set_value("Sales glossary")
        app.text_input(key=f"{prefix}_source").set_value("manual#1")
        app.text_input(key=f"{prefix}_scope").set_value("sales")
        app.text_area(key=f"{prefix}_text").set_value("Revenue is paid order value")
        self.click(app, "保存知识文档")
        identifier = self.config.load_knowledge()["documents"][0]["id"]
        app.text_area(key=f"doc_{identifier}_text").set_value("Revenue excludes refunds")
        self.click(app, "保存知识文档")
        self.assertEqual(len(self.config.load_knowledge()["documents"]), 1)
        app.text_input(key="knowledge_query").set_value("refunds")
        app.button(key="knowledge_preview").click().run()
        self.assertIn("Revenue excludes refunds", " ".join(item.value for item in app.json))

    def test_node_prompt_form_saves_actual_runtime_configuration(self):
        app = self.page("llm_config.py")
        next(box for box in app.selectbox if box.label == "工作流节点").set_value("planning").run()
        app.text_area(key="node_prompt_planning").set_value("Check time and units before comparing")
        self.click(app, "保存节点配置")
        self.assertEqual(self.config.load_workflow_config()["nodes"]["planning"]["prompt_template"],
                         "Check time and units before comparing")
        app.run()
        self.assertEqual(app.text_area(key="node_prompt_planning").value, "Check time and units before comparing")

    def test_method_steps_and_similar_question_forms_follow_publication_flow(self):
        app = self.page("semantics.py")
        self.knowledge_template(app, "methods")
        prefix = "method___new__"
        app.text_input(key=f"{prefix}_title").set_value("Revenue investigation")
        app.text_area(key=f"{prefix}_description").set_value("Investigate sales changes")
        app.session_state[f"{prefix}_steps"] = {
            "edited_rows": {0: {"description": "Check paid orders"}},
            "added_rows": [{"step_id": 2, "step_type": "llm_analysis",
                            "description": "Compare evidence", "dependencies": "1"}], "deleted_rows": [],
        }
        self.click(app, "保存分析方法")
        methods = self.config.load_methods()["methods"]
        self.assertEqual(len(methods), 1)
        identifier = methods[0]["id"]
        self.assertEqual(methods[0]["template"]["steps"][1]["analysis_requirements"]["input_data"], [1])
        prefix = f"method_{identifier}"
        app.selectbox(key=f"{prefix}_status").set_value("validated")
        app.text_input(key=f"{prefix}_reviewer").set_value("QA reviewer")
        app.text_input(key=f"{prefix}_fixtures").set_value("sales-fixture-1")
        app.checkbox(key=f"{prefix}_passed").check()
        self.click(app, "保存分析方法")
        app.selectbox(key=f"{prefix}_status").set_value("published")
        self.click(app, "保存分析方法")
        self.assertEqual(self.config.load_methods()["methods"][0]["status"], "published")
        prefix = f"case_{identifier}___new__"
        app.text_area(key=f"{prefix}_problem_structure").set_value("Rare seasonal conversion anomaly")
        app.text_area(key=f"{prefix}_adaptation").set_value("Bind current region and dates")
        app.selectbox(key=f"{prefix}_status").set_value("published")
        app.text_input(key=f"{prefix}_reviewer").set_value("QA reviewer")
        app.text_input(key=f"{prefix}_fixtures").set_value("case-fixture-1")
        app.checkbox(key=f"{prefix}_passed").check()
        self.click(app, "保存相似问题")
        from utils.analysis import MethodLibrary
        retrieved = MethodLibrary(self.config.load_methods()).retrieve("seasonal anomaly", [], {})
        self.assertEqual(retrieved[0]["id"], identifier)
        self.assertEqual(retrieved[0]["cases"][0]["adaptation"], "Bind current region and dates")

    def test_tools_split_builtin_and_mcp_without_duplicate_cards(self):
        app = self.page("tools.py")
        self.assertEqual([tab.label for tab in app.tabs], ["内置工具", "MCP 扩展"])
        self.assertIn("local:database.query", " ".join(item.label for item in app.tabs[0].expander))
        self.assertNotIn("local:database.query", " ".join(item.label for item in app.tabs[1].expander))
        self.assertTrue(any(key.key == "server_name_fetch" for key in app.tabs[1].text_input))
        content = " ".join(item.value for item in app.tabs[0].markdown)
        for engine in ("PostgreSQL (PGSQL)", "Microsoft SQL Server (MSSQL)", "MySQL", "AWS Athena"):
            self.assertIn(engine, content)

    def test_native_connector_buttons_open_matching_database_engine(self):
        for engine in ("postgresql", "mssql"):
            with self.subTest(engine=engine):
                app = self.page("tools.py")
                app.button(key=f"configure_{engine}").click().run()
                self.assertEqual(len(app.exception), 0, str(app.exception))
                self.assertEqual(app.selectbox(key="database_engine").value, engine)
                self.assertEqual(app.title[0].value, "数据库配置")
                self.assertNotIn("configure_engine", app.session_state)
        self.mcp.call_mcp_server_with_config.assert_not_called()

    @patch("utils.llm_client.LLMClient.list_models", return_value=["model-fast", "model-strong"])
    def test_refresh_models_and_role_dropdowns_reuse_global_connection(self, refresh):
        from utils.model_router import effective_model
        app = self.page("llm_config.py")
        app.button(key="refresh_models").click().run()
        refresh.assert_called_once()
        self.assertEqual(self.config.load_model_catalog()["models"], ["model-fast", "model-strong"])
        picker = next(box for box in app.selectbox if box.label == "全局默认型号")
        picker.set_value("model-fast")
        app.button(key="save_global_model").click().run()
        role_box = next(box for box in app.selectbox if (box.key or "").startswith("role_model_reasoning_"))
        role_box.set_value("model-strong")
        app.button(key="save_roles").click().run()
        self.assertEqual(self.config.load_model_roles()["reasoning"], {"model_name": "model-strong"})
        _, selected, origin, _ = effective_model(self.config, "reasoning")
        self.assertEqual(selected["openai"]["model"], "model-strong")
        self.assertEqual(selected["openai"]["api_key"], self.config.load_llm_config()["openai"]["api_key"])
        self.assertEqual(origin, "role_override")
        self.assertEqual(len([field for field in app.text_input if field.label == "API Key"]), 1)

    @patch("utils.llm_client.LLMClient.list_models", side_effect=RuntimeError("Model discovery unavailable"))
    def test_model_refresh_failure_does_not_save_draft_connection_or_invent_models(self, refresh):
        before = self.config.load_llm_config()
        app = self.page("llm_config.py")
        app.text_input(key="global_openai_base_url").set_value("http://invalid.example/v1")
        app.button(key="refresh_models").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("Model discovery unavailable", [error.value for error in app.error])
        self.assertEqual(self.config.load_model_catalog(), {})
        self.assertEqual(self.config.load_llm_config(), before)

    def test_prompt_defaults_restoration_and_profile_examples_save(self):
        from tests.test_profiles import profile
        from utils.prompts import DEFAULT_PROMPTS
        self.config.save_profile(profile())
        app = self.page("llm_config.py")
        app.session_state["resource_profile"] = "sales"
        app.run()
        app.selectbox(key="prompt_node").set_value("sql_generation").run()
        self.assertEqual(app.text_area(key="node_prompt_sql_generation").value, DEFAULT_PROMPTS["sql_generation"])
        app.selectbox(key="example_profile_sql_generation").set_value("sales").run()
        app.button(key="load_examples_sql_generation_sales").click().run()
        app.selectbox(key="example_mode_sql_generation").set_value("one_shot")
        app.text_area(key="node_prompt_sql_generation").set_value("Custom SQL instructions")
        app.button(key="save_node_sql_generation").click().run()
        settings = self.config.load_workflow_config()["nodes"]["sql_generation"]
        self.assertEqual(settings["prompt_template"], "Custom SQL instructions")
        self.assertEqual(settings["examples"][0]["profile_id"], "sales")
        self.assertEqual(settings["example_mode"], "one_shot")
        app.button(key="restore_prompt_sql_generation").click().run()
        self.assertEqual(app.text_area(key="node_prompt_sql_generation").value, DEFAULT_PROMPTS["sql_generation"])
        self.assertEqual(self.config.load_workflow_config()["nodes"]["sql_generation"]["prompt_template"], "Custom SQL instructions")

    def test_few_shot_added_rows_are_not_duplicated_after_save(self):
        from tests.test_profiles import profile
        self.config.save_profile(profile())
        legacy = {"profile_id": None, "input": "Legacy question", "output": "Legacy answer"}
        self.config.save_workflow_config({"nodes": {"sql_generation": {"examples": [legacy]}}})
        app = self.page("llm_config.py")
        app.session_state["resource_profile"] = "sales"
        app.run()
        app.selectbox(key="prompt_node").set_value("sql_generation").run()
        app.selectbox(key="example_profile_sql_generation").set_value("sales").run()
        app.button(key="load_examples_sql_generation_sales").click().run()
        app.session_state["examples_sql_generation_sales"] = {
            "edited_rows": {}, "deleted_rows": [],
            "added_rows": [{"input": "Return two without reading a table", "output": "SELECT 2 AS value"}],
        }
        app.selectbox(key="example_mode_sql_generation").set_value("few_shot")
        app.button(key="save_node_sql_generation").click().run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        settings = self.config.load_workflow_config()["nodes"]["sql_generation"]
        self.assertEqual(settings["example_mode"], "few_shot")
        self.assertEqual(len(settings["examples"]), 3)
        self.assertEqual(settings["examples"][0], legacy)
        self.assertEqual(settings["examples"][-1]["output"], "SELECT 2 AS value")
        app.button(key="save_node_sql_generation").click().run()
        self.assertEqual(self.config.load_workflow_config()["nodes"]["sql_generation"], settings)
        reloaded = self.page("llm_config.py")
        reloaded.session_state["resource_profile"] = "sales"
        reloaded.run()
        reloaded.selectbox(key="prompt_node").set_value("sql_generation").run()
        reloaded.selectbox(key="example_profile_sql_generation").set_value("sales").run()
        reloaded.button(key="save_node_sql_generation").click().run()
        self.assertEqual(len(reloaded.exception), 0, str(reloaded.exception))
        self.assertEqual(self.config.load_workflow_config()["nodes"]["sql_generation"], settings)

    @patch("utils.tool_management.shutil.which", return_value="/fixture/uvx")
    def test_one_click_mcp_verifies_lists_tools_and_toggle_persists(self, which):
        self.mcp.get_server_info.return_value = {"tools": [
            {"name": "fetch", "description": "Fetch URL", "inputSchema": {"type": "object"},
             "annotations": {"readOnlyHint": True}}]}
        app = self.page("tools.py")
        app.text_input(key="server_name_fetch").set_value("oneclick")
        app.checkbox(key="connect_consent_fetch").check().run()
        app.button(key="connect_fetch").click().run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        self.assertEqual(self.config.load_mcp_config()["oneclick"]["status"], "active")
        self.assertFalse(app.toggle(key="enabled_mcp:oneclick:fetch").value)
        app.toggle(key="enabled_mcp:oneclick:fetch").set_value(True).run()
        self.assertTrue(self.config.load_tools_config()["tools"]["mcp:oneclick:fetch"]["enabled"])
        app.toggle(key="enabled_mcp:oneclick:fetch").set_value(False).run()
        self.assertFalse(self.config.load_tools_config()["tools"]["mcp:oneclick:fetch"]["enabled"])
        self.mcp.get_server_info.assert_called_once()

    def test_advanced_json_examples_load_without_saving(self):
        app = self.page("semantics.py")
        self.assertEqual(len(app.tabs), 0)
        app.button(key="load_example_ontology").click().run()
        self.assertIn("record_count", app.text_area(key="advanced_ontology").value)
        self.assertEqual(self.config.load_semantics(), {})
        app.button(key="advanced_save_ontology").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("record_count", self.config.load_semantics()["metrics"])

    def test_query_knowledge_example_create_edit_delete(self):
        app = self.page("semantics.py")
        self.knowledge_template(app, "queries")
        app.button(key="query___new___example").click().run()
        self.assertIn("净销售额", app.text_input(key="query___new___question").value)
        self.assertEqual(self.config.load_query_knowledge(), {})
        app.button(key="query___new___save").click().run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        item = self.config.load_query_knowledge()["queries"][0]
        prefix = f"query_{item['id']}"
        self.assertEqual(item["visibility"], "shared")
        app.text_area(key=f"{prefix}_guidance").set_value("Updated handling, not old answers")
        app.button(key=f"{prefix}_save").click().run()
        self.assertEqual(self.config.load_query_knowledge()["queries"][0]["guidance"], "Updated handling, not old answers")
        self.assertTrue(app.button(key=f"{prefix}_delete_config").disabled)
        app.checkbox(key=f"{prefix}_delete_confirm").check().run()
        app.button(key=f"{prefix}_delete_config").click().run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        self.assertEqual(self.config.load_query_knowledge()["queries"], [])

    def test_sidebar_switch_hides_private_records_and_discards_unsaved_drafts(self):
        from tests.test_profiles import profile
        from tests.test_resource_scope import document
        for owner in ("a", "b"):
            self.config.save_profile(profile(owner))
        self.config.save_knowledge({"documents": [document("shared"), document("private-a", "a")]})
        app = AppTest.from_string(
            "import streamlit as st\n"
            "import runpy\n"
            "from utils.profile_ui import profile_selector\n"
            "with st.sidebar:\n    profile_selector()\n"
            f"runpy.run_path({str(PROJECT_ROOT / 'pages/semantics.py')!r})",
            default_timeout=15).run()
        app.selectbox(key="resource_profile").set_value("a").run()
        app.radio(key="knowledge_entry").set_value("documents:private-a").run()
        app.text_area(key="doc_private-a_text").set_value("unsaved A draft").run()
        app.selectbox(key="resource_profile").set_value("b").run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        self.assertNotIn("private-a", " ".join(app.radio(key="knowledge_entry").options))
        self.assertNotIn("unsaved A draft", " ".join(field.value for field in app.text_area))
        app.text_area(key="metrics___new___description").set_value("B-specific KPI")
        app.text_input(key="metrics___new___name").set_value("B-specific KPI")
        app.button(key="metrics___new___save").click().run()
        metric = next(iter(self.config.load_semantics()["metrics"].values()))
        self.assertEqual((metric["visibility"], metric["profile_id"]), ("profile", "b"))
        app.selectbox(key="resource_profile").set_value("a").run()
        self.assertNotIn("B-specific KPI", " ".join(app.radio(key="knowledge_entry").options))
        app.radio(key="knowledge_entry").set_value("documents:private-a").run()
        self.assertEqual(app.text_area(key="doc_private-a_text").value, "Sales policy excludes refunds")

    def test_manual_schema_fields_create_edit_delete_persist_without_live_database(self):
        app = self.page("schema_config.py")
        next(field for field in app.text_input if (field.key or "").endswith("_new_table")).set_value("manual_orders")
        next(button for button in app.button if (button.key or "").endswith("_add_table")).click().run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        self.assertEqual(next(box for box in app.selectbox if (box.key or "").endswith("_table")).value, "manual_orders")
        batch = next(key for key in app.session_state._state.filtered_state if "_batch_manual_orders" in key)
        app.session_state[batch] = {"edited_rows": {}, "deleted_rows": [], "added_rows": [
            {"name": " company_id ", "type": "varchar", "comment": None, "business_key": None},
            {"name": "net_amount", "type": "decimal", "comment": "Net sales"}]}
        next(button for button in app.button if (button.key or "").endswith("_apply_manual_orders")).click().run()
        self.click(app, "💾 保存所有表的Schema配置")
        saved = self.config.resolve_datasource("mysql")["schema"]["tables"]["manual_orders"]
        self.assertEqual([field["name"] for field in saved], ["company_id", "net_amount"])
        self.assertEqual(saved[0]["comment"], "")
        self.assertFalse(saved[0]["business_key"])
        batch = next(key for key in app.session_state._state.filtered_state if "_batch_manual_orders" in key)
        app.session_state[batch] = {"edited_rows": {0: {"name": "company_key", "comment": "Unique company"}},
                                   "deleted_rows": [1], "added_rows": []}
        next(button for button in app.button if (button.key or "").endswith("_apply_manual_orders")).click().run()
        self.click(app, "💾 保存所有表的Schema配置")
        reloaded = self.page("schema_config.py")
        saved = self.config.resolve_datasource("mysql")["schema"]["tables"]["manual_orders"]
        self.assertEqual([(field["name"], field["comment"]) for field in saved], [("company_key", "Unique company")])
        next(box for box in reloaded.selectbox if (box.key or "").endswith("_table")).set_value("manual_orders").run()
        next(box for box in reloaded.checkbox if (box.key or "").endswith("_manual_orders_delete_confirm")).check().run()
        next(button for button in reloaded.button if (button.key or "").endswith("_manual_orders_delete")).click().run()
        self.assertEqual(len(reloaded.exception), 0, str(reloaded.exception))
        self.assertNotIn("manual_orders", self.config.resolve_datasource("mysql")["schema"]["tables"])
        self.mcp.get_tables.assert_not_called()
        self.mcp.describe_table.assert_not_called()

    def test_method_step_added_rows_not_duplicated_and_case_deletion(self):
        app = self.page("semantics.py")
        self.knowledge_template(app, "methods")
        app.text_input(key="method___new___title").set_value("Compare")
        app.text_area(key="method___new___description").set_value("Compare periods")
        self.click(app, "保存分析方法")
        identifier = self.config.load_methods()["methods"][0]["id"]
        prefix = f"method_{identifier}"
        app.session_state[f"{prefix}_steps"] = {
            "edited_rows": {0: {"description": "First query"}}, "deleted_rows": [],
            "added_rows": [{"step_id": 2, "step_type": "sql_query", "description": "Second query", "dependencies": ""}]}
        self.click(app, "保存分析方法")
        self.click(app, "保存分析方法")
        self.assertFalse(app.error)
        self.assertEqual(len(self.config.load_methods()["methods"][0]["template"]["steps"]), 2)
        prefix = f"case_{identifier}___new__"
        app.button(key=f"{prefix}_example").click().run()
        self.click(app, "保存相似问题")
        case_id = self.config.load_methods()["methods"][0]["cases"][0]["id"]
        prefix = f"case_{identifier}_{case_id}"
        app.text_area(key=f"{prefix}_adaptation").set_value("Updated current parameters")
        self.click(app, "保存相似问题")
        self.assertEqual(self.config.load_methods()["methods"][0]["cases"][0]["adaptation"], "Updated current parameters")
        app.checkbox(key=f"{prefix}_delete_confirm").check().run()
        app.button(key=f"{prefix}_delete_config").click().run()
        self.assertEqual(self.config.load_methods()["methods"][0]["cases"], [])
        app.checkbox(key=f"method_{identifier}_delete_confirm").check().run()
        app.button(key=f"method_{identifier}_delete_config").click().run()
        self.assertEqual(self.config.load_methods()["methods"], [])
        self.assertEqual(len(app.exception), 0, str(app.exception))

    def test_draft_profile_can_be_created_before_private_resources(self):
        app = self.page("profiles.py")
        app.text_input(key="profile___new___name").set_value("New department")
        self.click(app, "保存 Profile")
        identifier = next(iter(self.config.load_profiles()))
        self.assertEqual(self.config.load_profiles()[identifier]["status"], "draft")
        app.checkbox(key=f"profile_{identifier}_draft").uncheck()
        self.click(app, "保存 Profile")
        self.assertTrue(app.error)
        app.multiselect(key=f"profile_{identifier}_sources").set_value(["legacy-mysql"]).run()
        app.multiselect(key=f"profile_{identifier}_tables_legacy-mysql").set_value(["mysql_orders"])
        self.click(app, "保存 Profile")
        self.assertEqual(self.config.load_profiles()[identifier]["status"], "active")

    def test_connection_metadata_hides_private_tables_and_delete_is_config_only(self):
        from tests.test_profiles import profile
        self.config.save_profile(profile("a"))
        source = self.config.resolve_datasource("mysql")
        source["schema"]["tables"]["private_orders"] = [{"name": "private"}]
        source["schema"]["table_scopes"] = {"private_orders": {"visibility": "profile", "profile_id": "a"}}
        self.config.save_datasource(source)
        with patch("utils.datasources.DatabaseAdapter") as adapter:
            adapter.return_value.metadata.return_value = {"tables": ["mysql_orders", "private_orders"]}
            app = self.page("database_config.py")
            self.click(app, "🔍 测试连接")
            self.assertNotIn("private_orders", " ".join(item.value for item in app.json))
            app.selectbox[0].set_value("athena").run()
            app.checkbox(key="legacy-athena__delete_confirm").check().run()
            app.button(key="legacy-athena__delete_config").click().run()
            self.assertEqual(len(app.exception), 0, str(app.exception))
            self.assertNotIn("legacy-athena", self.config.load_datasources())
            adapter.return_value.execute.assert_not_called()

    def test_metric_four_fields_have_examples_and_load_only_into_draft(self):
        app = self.page("semantics.py")
        prefix = "metrics___new__"
        self.assertEqual(app.text_input(key=f"{prefix}_name").label, "1. KPI / 业务指标名称")
        self.assertEqual(app.text_area(key=f"{prefix}_description").label, "2. KPI / 业务指标定义")
        self.assertEqual(app.text_area(key=f"{prefix}_subject").label, "3. 统计对象（可选）")
        self.assertEqual(app.text_area(key=f"{prefix}_dimension_notes").label, "4. 分析维度（可选）")
        app.button(key=f"{prefix}_example").click().run()
        self.assertEqual(app.text_input(key=f"{prefix}_name").value, "净销售额")
        self.assertIn("公司", app.text_area(key=f"{prefix}_subject").value)
        self.assertIn("月份", app.text_area(key=f"{prefix}_dimension_notes").value)
        self.assertEqual(self.config.load_semantics(), {})
        app.button(key=f"{prefix}_save").click().run()
        item = next(iter(self.config.load_semantics()["metrics"].values()))
        self.assertEqual(item["name"], "净销售额")
        self.assertNotIn("allowed_dimensions", item)
        self.assertIn("订单明细", item["subject"])

    def test_legacy_metric_rename_keeps_id_empty_allowlist_and_json_in_sync(self):
        self.config.save_semantics({"metrics": {"legacy": {"description": "Old definition", "allowed_dimensions": []}}})
        app = self.page("semantics.py")
        app.radio(key="knowledge_entry").set_value("metrics:legacy").run()
        app.text_input(key="metrics_legacy_name").set_value("New display name")
        app.text_area(key="metrics_legacy_subject").set_value("Companies")
        app.button(key="metrics_legacy_save").click().run()
        saved = self.config.load_semantics()["metrics"]["legacy"]
        self.assertEqual(saved["allowed_dimensions"], [])
        self.assertEqual(app.radio(key="knowledge_entry").value, "metrics:legacy")
        self.assertIn("New display name", app.text_area(key="entry_json_metrics:legacy").value)
        edited = {**saved, "description": "Updated through JSON"}
        app.text_area(key="entry_json_metrics:legacy").set_value(json.dumps(edited))
        app.button(key="entry_json_save_metrics:legacy").click().run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        self.assertEqual(app.text_area(key="metrics_legacy_description").value, "Updated through JSON")
        self.assertEqual(list(self.config.load_semantics()["metrics"]), ["legacy"])

    def test_guide_examples_are_editable_without_duplicate_rows_after_save(self):
        app = self.page("semantics.py")
        self.knowledge_template(app, "queries")
        app.button(key="query___new___example").click().run()
        app.button(key="query___new___examples_seed").click().run()
        app.button(key="query___new___save").click().run()
        identifier = self.config.load_query_knowledge()["queries"][0]["id"]
        prefix = f"query_{identifier}"
        app.multiselect(key=f"{prefix}_stages").set_value(["planning"])
        app.session_state[f"{prefix}_examples"] = {
            "edited_rows": {0: {"guidance": "Bind current company and dates"}}, "deleted_rows": [],
            "added_rows": [{"question": "Unusual cohort anomaly", "guidance": "Compare current cohorts"}]}
        app.button(key=f"{prefix}_save").click().run()
        app.button(key=f"{prefix}_save").click().run()
        self.assertEqual(len(app.exception), 0, str(app.exception))
        item = self.config.load_query_knowledge()["queries"][0]
        self.assertEqual(len(item["examples"]), 2)
        self.assertEqual(item["examples"][0]["guidance"], "Bind current company and dates")
        self.assertEqual(item["retrieval_stages"], ["planning"])
        app.text_input(key="knowledge_query").set_value("Unusual cohort anomaly")
        app.selectbox(key="knowledge_preview_stage").set_value("planning")
        app.button(key="knowledge_preview").click().run()
        self.assertIn("Compare current cohorts", " ".join(element.value for element in app.json))
        self.llm.generate_response.assert_not_called()

    def test_catalog_filters_and_rename_keep_saved_entry_selected(self):
        from tests.test_resource_scope import document
        self.config.save_knowledge({"documents": [document("legacy-reference")]})
        self.config.save_semantics({"metrics": {"metric": {"description": "A metric"}}})
        app = self.page("semantics.py")
        app.selectbox(key="knowledge_type_filter").set_value("references").run()
        self.assertNotIn("metric", " ".join(app.radio(key="knowledge_entry").options))
        app.text_input(key="knowledge_search").set_value("legacy").run()
        app.radio(key="knowledge_entry").set_value("documents:legacy-reference").run()
        app.text_input(key="doc_legacy-reference_title").set_value("Renamed reference")
        self.click(app, "保存知识文档")
        self.assertEqual(app.radio(key="knowledge_entry").value, "documents:legacy-reference")
        self.assertIn("Renamed reference", " ".join(app.radio(key="knowledge_entry").options))
        self.assertEqual(app.text_input(key="knowledge_search").value, "")
        bad = {**self.config.load_knowledge()["documents"][0], "id": "changed-id"}
        app.text_area(key="entry_json_documents:legacy-reference").set_value(json.dumps(bad))
        app.button(key="entry_json_save_documents:legacy-reference").click().run()
        self.assertTrue(app.error)
        self.assertEqual(self.config.load_knowledge()["documents"][0]["id"], "legacy-reference")

    def test_guide_opens_linked_method_and_manages_cases_in_same_center(self):
        from tests.test_resource_scope import method
        self.config.save_methods({"methods": [method()]})
        self.config.save_query_knowledge({"queries": [{
            "id": "guide", "question": "Company sales", "guidance": "Compare periods",
            "bindings": {"methods": ["compare"]}}]})
        app = self.page("semantics.py")
        app.radio(key="knowledge_entry").set_value("queries:guide").run()
        app.button(key="query_guide_open_compare").click().run()
        self.assertEqual(app.radio(key="knowledge_entry").value, "methods:compare")
        app.button(key="case_compare___new___example").click().run()
        self.click(app, "保存相似问题")
        cases = self.config.load_methods()["methods"][0]["cases"]
        self.assertEqual(len(cases), 1)
        self.assertEqual(app.radio(key="knowledge_entry").value, "methods:compare")
        app.radio(key="knowledge_entry").set_value(f"cases:compare:{cases[0]['id']}").run()
        app.button(key="open_case_method").click().run()
        self.assertEqual(app.radio(key="knowledge_entry").value, "methods:compare")

    def test_profile_draft_reset_preserves_language_and_history(self):
        app = AppTest.from_string(
            "import streamlit as st\n"
            "from utils.profile_ui import reset_profile_drafts\n"
            "st.session_state.update(language='en', language_selector='English', resource_profile='sales',\n"
            "    run_sessions={'sales':'conversation'}, open_run_id='run-id', unsaved_draft='discard')\n"
            "reset_profile_drafts()\n"
            "st.write(st.session_state.get('language'))\n").run()
        self.assertEqual(app.session_state["language"], "en")
        self.assertEqual(app.session_state["language_selector"], "English")
        self.assertEqual(app.session_state["run_sessions"], {"sales": "conversation"})
        self.assertEqual(app.session_state["open_run_id"], "run-id")
        self.assertNotIn("unsaved_draft", app.session_state._state.filtered_state)

    def test_profile_label_refresh_does_not_discard_same_scope_drafts(self):
        app = AppTest.from_string(
            "import streamlit as st\n"
            "from utils.profile_ui import profile_changed\n"
            "st.session_state.update(language='en', resource_profile=None, _config_profile=None,\n"
            "    unsaved_draft='keep')\n"
            "profile_changed()\n"
            "st.write(st.session_state.get('unsaved_draft'))\n").run()
        self.assertEqual(app.session_state["unsaved_draft"], "keep")
        self.assertEqual(app.session_state["language"], "en")
