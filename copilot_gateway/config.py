"""Configuration loading: YAML file + environment variable overrides."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 3001
    log_level: str = "info"
    api_key: str = ""


@dataclass
class CopilotConfig:
    default_model: str = "gpt-4o"
    cli_path: str = ""
    session_idle_timeout: int = 7200


@dataclass
class ModelsConfig:
    cache_ttl: int = 300


@dataclass
class ToolsConfig:
    enabled: list[str] = field(default_factory=lambda: [
        "copilot_gateway.tools.builtins.get_time",
        "copilot_gateway.tools.builtins.web_search",
    ])


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    copilot: CopilotConfig = field(default_factory=CopilotConfig)
    models: ModelsConfig = field(default_factory=ModelsConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml(path: str | Path) -> dict:
    """Load a YAML config file. Returns empty dict if file doesn't exist."""
    p = Path(path)
    if not p.is_file():
        return {}
    with open(p) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        logging.getLogger(__name__).warning("Config file %s did not parse as a dict, ignoring", path)
        return {}
    return data


def _apply_env_overrides(data: dict) -> dict:
    """Apply environment variable overrides to config dict."""
    env_map = {
        "HOST": ("server", "host"),
        "PORT": ("server", "port"),
        "LOG_LEVEL": ("server", "log_level"),
        "COPILOT_API_KEY": ("server", "api_key"),
        "DEFAULT_MODEL": ("copilot", "default_model"),
        "COPILOT_CLI_PATH": ("copilot", "cli_path"),
    }
    for env_key, path in env_map.items():
        value = os.environ.get(env_key)
        if value is None:
            continue
        section, key = path
        if section not in data:
            data[section] = {}
        # Convert port to int
        if key == "port":
            try:
                value = int(value)
            except ValueError:
                continue
        data[section][key] = value
    return data


def _dict_to_config(data: dict) -> AppConfig:
    """Convert a config dict to an AppConfig dataclass."""
    return AppConfig(
        server=ServerConfig(**data.get("server", {})),
        copilot=CopilotConfig(**data.get("copilot", {})),
        models=ModelsConfig(**data.get("models", {})),
        tools=ToolsConfig(**data.get("tools", {})),
    )


def load_config() -> AppConfig:
    """Load configuration from YAML file and environment variables.

    Priority: env vars > YAML file > defaults.
    """
    config_path = os.environ.get("CONFIG_PATH", "/config/config.yaml")

    data = _load_yaml(config_path)
    data = _apply_env_overrides(data)

    return _dict_to_config(data)
