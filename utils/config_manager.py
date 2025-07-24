import json
import os
from typing import Dict, Any

class ConfigManager:
    def __init__(self):
        self.config_dir = "config"
        os.makedirs(self.config_dir, exist_ok=True)
    
    def _load_config(self, filename: str) -> Dict[str, Any]:
        filepath = os.path.join(self.config_dir, filename)
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def _save_config(self, filename: str, config: Dict[str, Any]):
        filepath = os.path.join(self.config_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    
    def load_llm_config(self) -> Dict[str, Any]:
        config = self._load_config("llm_config.json")
        return config.get("llm_config", {})
    
    def save_llm_config(self, config: Dict[str, Any]):
        self._save_config("llm_config.json", {"llm_config": config})
    
    def load_database_config(self) -> Dict[str, Any]:
        config = self._load_config("database_config.json")
        return config.get("databases", {})
    
    def save_database_config(self, db_type: str, config: Dict[str, Any]):
        existing = self._load_config("database_config.json")
        if "databases" not in existing:
            existing["databases"] = {}
        existing["databases"][db_type] = config
        self._save_config("database_config.json", existing)
    
    def load_mcp_config(self) -> Dict[str, Any]:
        config = self._load_config("mcp_config.json")
        return config.get("mcp_servers", {})
    
    def save_mcp_config(self, config: Dict[str, Any]):
        self._save_config("mcp_config.json", {"mcp_servers": config})
    
    def load_schema_config(self) -> Dict[str, Any]:
        config = self._load_config("schema_config.json")
        return config.get("schemas", {})
    
    def save_schema_config(self, database: str, config: Dict[str, Any]):
        existing = self._load_config("schema_config.json")
        if "schemas" not in existing:
            existing["schemas"] = {}
        existing["schemas"][database] = config
        self._save_config("schema_config.json", existing)