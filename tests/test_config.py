"""Tests for the config module."""

from __future__ import annotations

import os
from unittest import mock

import pytest

from copilot_gateway.config import (
    AppConfig,
    _apply_env_overrides,
    _deep_merge,
    _dict_to_config,
    load_config,
)


class TestDeepMerge:
    def test_flat_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        assert _deep_merge(base, override) == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"server": {"host": "0.0.0.0", "port": 3001}}
        override = {"server": {"port": 8080}}
        result = _deep_merge(base, override)
        assert result == {"server": {"host": "0.0.0.0", "port": 8080}}

    def test_does_not_mutate_base(self):
        base = {"a": 1}
        override = {"a": 2}
        _deep_merge(base, override)
        assert base == {"a": 1}


class TestApplyEnvOverrides:
    def test_port_override(self):
        data = {"server": {"port": 3001}}
        with mock.patch.dict(os.environ, {"PORT": "8080"}):
            result = _apply_env_overrides(data)
        assert result["server"]["port"] == 8080

    def test_invalid_port_ignored(self):
        data = {"server": {"port": 3001}}
        with mock.patch.dict(os.environ, {"PORT": "not-a-number"}):
            result = _apply_env_overrides(data)
        assert result["server"]["port"] == 3001

    def test_api_key_override(self):
        data = {}
        with mock.patch.dict(os.environ, {"COPILOT_API_KEY": "sk-test-123"}):
            result = _apply_env_overrides(data)
        assert result["server"]["api_key"] == "sk-test-123"

    def test_model_override(self):
        data = {}
        with mock.patch.dict(os.environ, {"DEFAULT_MODEL": "gpt-5"}):
            result = _apply_env_overrides(data)
        assert result["copilot"]["default_model"] == "gpt-5"

    def test_no_env_no_change(self):
        data = {"server": {"host": "localhost"}}
        with mock.patch.dict(os.environ, {}, clear=True):
            result = _apply_env_overrides(data)
        assert result == {"server": {"host": "localhost"}}


class TestDictToConfig:
    def test_defaults(self):
        cfg = _dict_to_config({})
        assert cfg.server.host == "0.0.0.0"
        assert cfg.server.port == 3001
        assert cfg.server.api_key == ""
        assert cfg.copilot.default_model == "gpt-4o"
        assert cfg.models.cache_ttl == 300

    def test_custom_values(self):
        data = {
            "server": {"host": "127.0.0.1", "port": 8080, "api_key": "mykey"},
            "copilot": {"default_model": "gpt-5"},
        }
        cfg = _dict_to_config(data)
        assert cfg.server.host == "127.0.0.1"
        assert cfg.server.port == 8080
        assert cfg.server.api_key == "mykey"
        assert cfg.copilot.default_model == "gpt-5"


class TestLoadConfig:
    def test_loads_with_defaults_when_no_file(self):
        with mock.patch.dict(os.environ, {"CONFIG_PATH": "/nonexistent/path.yaml"}, clear=False):
            cfg = load_config()
        assert isinstance(cfg, AppConfig)
        assert cfg.server.port == 3001
