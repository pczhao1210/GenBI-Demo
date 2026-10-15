import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Any

from filelock import FileLock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

class ConfigManager:
    def __init__(self, config_dir=None):
        self.config_dir = Path(config_dir) if config_dir is not None else PROJECT_ROOT / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)
    
    def _load_config(self, filename: str) -> Dict[str, Any]:
        filepath = self.config_dir / filename
        if not filepath.exists():
            return {}
        with filepath.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Configuration must be an object: {filename}")
        return data
    
    def _save_config(self, filename: str, config: Dict[str, Any]):
        filepath = self.config_dir / filename
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.config_dir,
                                             suffix=".tmp", delete=False) as f:
                temp_path = Path(f.name)
                json.dump(config, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, filepath)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    
    def load_llm_config(self) -> Dict[str, Any]:
        config = self._load_config("llm_config.json")
        return config.get("llm_config", {})
    
    def save_llm_config(self, config: Dict[str, Any]):
        self._save_config("llm_config.json", {"llm_config": config})
    
    def load_database_config(self) -> Dict[str, Any]:
        config = self._load_config("database_config.json")
        return config.get("databases", {})
    
    def save_database_config(self, db_type: str, config: Dict[str, Any]):
        with FileLock(str(self.config_dir / "database_config.json.lock")):
            existing = self._load_config("database_config.json")
            existing.setdefault("databases", {})[db_type] = config
            self._save_config("database_config.json", existing)
    
    def load_mcp_config(self) -> Dict[str, Any]:
        config = self._load_config("mcp_config.json")
        
        # 如果配置为空，尝试从示例配置初始化
        if not (self.config_dir / "mcp_config.json").exists():
            example_config = self._load_config("example_mcp_config.json")
            if example_config.get("mcp_servers"):
                # 复制示例配置到实际配置
                self.save_mcp_config(example_config["mcp_servers"])
                config = example_config
        
        return config.get("mcp_servers", {})
    
    def save_mcp_config(self, config: Dict[str, Any]):
        self._save_config("mcp_config.json", {"mcp_servers": config})
    
    def load_schema_config(self) -> Dict[str, Any]:
        config = self._load_config("schema_config.json")
        return config.get("schemas", {})
    
    def save_schema_config(self, database: str, config: Dict[str, Any]):
        with FileLock(str(self.config_dir / "schema_config.json.lock")):
            existing = self._load_config("schema_config.json")
            existing.setdefault("schemas", {})[database] = config
            self._save_config("schema_config.json", existing)