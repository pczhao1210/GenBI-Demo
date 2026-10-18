from copy import deepcopy

from utils.tool_catalog import version_of


def model_section(config):
    provider = config.get("provider", "openai")
    return "openai" if provider == "openai_sdk" else provider


def model_name(config):
    section = model_section(config)
    return config.get(section, {}).get("deployment_name" if section == "azure_openai" else "model", "")


def with_model(config, name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Select a model from the available model list")
    result = deepcopy(config)
    section = model_section(result)
    result.setdefault(section, {})["deployment_name" if section == "azure_openai" else "model"] = name
    return result


def connection_version(config):
    section = model_section(config)
    return version_of({"provider": config.get("provider"),
                      "connection": {key: value for key, value in config.get(section, {}).items()
                                     if key not in ("model", "deployment_name")}})


def available_models(config, catalog):
    return list(catalog.get("models", [])) if catalog.get("connection_version") == connection_version(config) else []
