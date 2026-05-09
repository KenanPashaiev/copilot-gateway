# Configuration Reference

copilot-gateway is configured through a combination of a **YAML config file** and **environment variables**. Environment variables always take precedence over YAML values, which take precedence over built-in defaults.

## Config File

By default, the gateway looks for a config file at `/config/config.yaml` inside the container. Override this path with the `CONFIG_PATH` environment variable.

If no config file is found, the gateway starts with built-in defaults — no config file is required.

```yaml
# config.yaml — full example with all options

server:
  host: "0.0.0.0"
  port: 3001
  log_level: "info"

copilot:
  default_model: "gpt-4o"
  cli_path: ""

models:
  cache_ttl: 300

tools:
  enabled:
    - copilot_gateway.tools.builtins.get_time
    - copilot_gateway.tools.builtins.web_search
```

## All Options

### server

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `host` | string | `0.0.0.0` | `HOST` | Address to bind to. Use `0.0.0.0` for Docker, `127.0.0.1` for local dev. |
| `port` | int | `3001` | `PORT` | Port to listen on. |
| `log_level` | string | `info` | `LOG_LEVEL` | Log level: `debug`, `info`, `warning`, `error`. |

### copilot

| Key | Type | Default | Env Override | Description |
|-----|------|---------|-------------|-------------|
| `default_model` | string | `gpt-4o` | `DEFAULT_MODEL` | Model to use when the request doesn't specify one. |
| `cli_path` | string | `""` (bundled) | `COPILOT_CLI_PATH` | Path to Copilot CLI binary. Leave empty to use the SDK-bundled CLI. |

### models

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `cache_ttl` | int | `300` | Seconds to cache the model list before refreshing from the SDK. |

### tools

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | list[string] | See below | List of Python module paths to load as tools. |

Default `tools.enabled`:
```yaml
tools:
  enabled:
    - copilot_gateway.tools.builtins.get_time
    - copilot_gateway.tools.builtins.web_search
```

## Environment Variables

These environment variables are always checked and override the corresponding YAML values:

| Variable | Overrides | Example |
|----------|-----------|---------|
| `COPILOT_GITHUB_TOKEN` | Copilot SDK auth | `ghp_abc123...` |
| `HOST` | `server.host` | `127.0.0.1` |
| `PORT` | `server.port` | `8080` |
| `LOG_LEVEL` | `server.log_level` | `debug` |
| `DEFAULT_MODEL` | `copilot.default_model` | `claude-sonnet-4` |
| `COPILOT_CLI_PATH` | `copilot.cli_path` | `/usr/local/bin/copilot` |
| `CONFIG_PATH` | Config file location | `/config/config.yaml` |

## Priority

```
Environment variables  (highest)
        ↓
YAML config file
        ↓
Built-in defaults      (lowest)
```

## Minimal Setup

The simplest possible setup — no config file, just one env var:

```bash
docker run -d -p 3001:3001 -e COPILOT_GITHUB_TOKEN=ghp_xxx copilot-gateway:latest
```

This uses all defaults: binds to `0.0.0.0:3001`, model `gpt-4o`, both built-in tools enabled.
