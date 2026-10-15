import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from utils.config_manager import ConfigManager, PROJECT_ROOT


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="genbi-tests-")
        self.addCleanup(temporary.cleanup)
        self.config = ConfigManager(Path(temporary.name))
        self.config.save_database_config("mysql", {"database": "mysql_test", "host": "localhost"})
        self.config.save_database_config("athena", {"database": "athena_test", "region": "us-east-1"})
        for database in ("mysql", "athena"):
            self.config.save_schema_config(database, {
                "tables": {f"{database}_orders": [{"name": "updated_at", "type": "timestamp"}]},
                "descriptions": {},
            })
        self.config.save_llm_config({"provider": "openai", "openai": {
            "model": "gpt-4o", "api_key": "test-key", "base_url": "http://example.invalid/v1",
        }})
        self.config.save_mcp_config(json.loads(
            (PROJECT_ROOT / "config/example_mcp_config.json").read_text()
        )["mcp_servers"])
        self.mcp = Mock()
        self.llm = Mock()


def query_response(rows=None):
    return {"result": {"success": True, "data": {
        "columns": ["n"], "rows": [[1]] if rows is None else rows,
        "row_count": 1, "truncated": False,
    }}}
