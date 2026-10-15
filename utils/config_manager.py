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
        if (self.config_dir / "datasources.json").exists() and db_type in ("mysql", "athena"):
            source = self.resolve_datasource(db_type)
            self.save_datasource({**source, "config": config})
    
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
        schemas = config.get("schemas", {})
        catalog = self._load_config("datasources.json").get("sources", {})
        if catalog:
            schemas = {key: value["schema"] for key, value in catalog.items()}
            for engine in ("mysql", "athena", "postgresql", "mssql"):
                matches = [value for value in catalog.values() if value["engine"] == engine]
                if len(matches) == 1:
                    schemas[engine] = matches[0]["schema"]
        return schemas
    
    def save_schema_config(self, database: str, config: Dict[str, Any]):
        if (self.config_dir / "datasources.json").exists():
            source = self.resolve_datasource(database)
            self.save_datasource({**source, "schema": config})
            return
        with FileLock(str(self.config_dir / "schema_config.json.lock")):
            existing = self._load_config("schema_config.json")
            existing.setdefault("schemas", {})[database] = config
            self._save_config("schema_config.json", existing)

    def load_datasources(self):
        from utils.datasources import normalize_engine
        with FileLock(str(self.config_dir / "datasources.json.lock")):
            catalog = self._load_config("datasources.json")
            if not catalog:
                schemas = self._load_config("schema_config.json").get("schemas", {})
                sources, legacy = {}, {}
                for engine, connection in self.load_database_config().items():
                    if engine not in ("mysql", "athena"):
                        continue
                    source_id = f"legacy-{engine}"
                    sources[source_id] = {
                        "datasource_id": source_id, "name": engine, "engine": normalize_engine(engine),
                        "config": connection, "schema": schemas.get(engine, {}),
                        "timezone": "UTC", "business_day_start": 0, "config_version": 1,
                        "schema_version": 1, "description": "", "tags": [],
                    }
                    legacy[engine] = source_id
                catalog = {"version": 1, "sources": sources, "legacy_mapping": legacy}
                self._save_config("datasources.json", catalog)
        return catalog["sources"]

    def resolve_datasource(self, identifier):
        from utils.datasources import resolve_source
        return resolve_source(self.load_datasources(), identifier)

    def save_datasource(self, source):
        from utils.datasources import validate_source
        source = validate_source(source)
        self.load_datasources()
        with FileLock(str(self.config_dir / "datasources.json.lock")):
            catalog = self._load_config("datasources.json")
            old = catalog["sources"].get(source["datasource_id"], {})
            source["config_version"] = old.get("config_version", 0) + (old.get("config") != source["config"])
            source["schema_version"] = old.get("schema_version", 0) + (old.get("schema") != source["schema"])
            catalog["sources"][source["datasource_id"]] = source
            self._save_config("datasources.json", catalog)
        return source

    def load_semantics(self):
        return self._load_config("semantics.json")

    def save_semantics(self, semantics):
        from utils.semantics import validate_ontology
        validate_ontology(semantics, self.load_datasources())
        self._save_config("semantics.json", semantics)

    def load_knowledge(self):
        return self._load_config("knowledge.json")

    def save_knowledge(self, knowledge):
        from utils.semantics import validate_knowledge
        validate_knowledge(knowledge)
        self._save_config("knowledge.json", knowledge)

    def load_model_roles(self):
        return self._load_config("model_roles.json")

    def save_model_roles(self, roles):
        if not isinstance(roles, dict) or set(roles) - {"fast", "sql", "reasoning"}:
            raise ValueError("Model roles must be fast, sql or reasoning")
        for config in roles.values():
            if not isinstance(config, dict) or not config.get("provider"):
                raise ValueError("Each role requires a complete LLM provider configuration")
        self._save_config("model_roles.json", roles)

    def load_methods(self):
        return self._load_config("methods.json")

    def save_methods(self, library):
        from utils.analysis import validate_methods
        validate_methods(library, self.load_methods())
        self._save_config("methods.json", library)