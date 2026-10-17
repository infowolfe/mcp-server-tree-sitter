# MCP Tree-sitter Server CLI Guide

This document explains the command-line interface (CLI) for the MCP Tree-sitter Server, including available options and usage patterns.

## Command-Line Arguments

The MCP Tree-sitter Server provides a command-line interface with several options:

```bash
mcp-server-tree-sitter [options]
```

### Available Options

| Option | Description |
|--------|-------------|
| `--help` | Show help message and exit |
| `--version` | Show version information and exit |
| `--config CONFIG` | Path to configuration file |
| `--debug` | Enable debug logging |
| `--disable-cache` | Disable parse tree caching |
| `--transport TRANSPORT` | `stdio`, `sse`, or `streamable-http`. Overrides the config file only when passed |
| `--host HOST` | HTTP listen address. Overrides the config file only when passed |
| `--port PORT` | HTTP listen port. Overrides the config file only when passed |
| `--mount-path PATH` | Streamable HTTP route, such as `/mcp`. Overrides the config file only when passed |
| `--server` / `--no-server` | Listen persistently, or stay on stdio. Overrides the config file only when passed |
| `--socket PATH` | Unix socket path. Replaces host and port. Overrides the config file only when passed |

The same service values load from the `service` section of `~/.config/tree-sitter-mcp/config.yaml`. Defaults are `server: false`, transport `stdio`, host `127.0.0.1`, port `8765`, mount path `/mcp`, and no socket. `MCP_TS_SERVICE_SERVER`, `MCP_TS_SERVICE_SOCKET`, `MCP_TS_SERVICE_TRANSPORT`, `MCP_TS_SERVICE_HOST`, `MCP_TS_SERVICE_PORT`, and `MCP_TS_SERVICE_MOUNT_PATH` override the file. A CLI flag overrides the file only when you pass it, and an environment variable still wins over that flag.

The process listens only when `server` is true or `--server` is passed. `server: true` with transport `stdio` listens as `streamable-http`. `streamable-http` serves `mount_path`. `sse` listens on the SDK paths `/sse` and `/messages/`. `--socket` listens on that Unix socket instead of host and port. A leftover socket file is removed. A path another process is still accepting on is refused. A second start of this server also refuses the path while `{path}.lock` is held.

### Examples

Display help information:
```bash
mcp-server-tree-sitter --help
```

Show version information:
```bash
mcp-server-tree-sitter --version
```

Run with a custom configuration file:
```bash
mcp-server-tree-sitter --config /path/to/config.yaml
```

Enable debug logging:
```bash
mcp-server-tree-sitter --debug
```

Disable parse tree caching:
```bash
mcp-server-tree-sitter --disable-cache
```

## Running with MCP

The server can also be run using the MCP command-line interface:

```bash
# Run the server
mcp run mcp_server_tree_sitter.server

# Run with the MCP Inspector
mcp dev mcp_server_tree_sitter.server
```

You can pass the same arguments to these commands:

```bash
# Enable debug logging
mcp run mcp_server_tree_sitter.server --debug

# Use a custom configuration file with the inspector
mcp dev mcp_server_tree_sitter.server --config /path/to/config.yaml
```

## Using Makefile Targets

For convenience, the project provides Makefile targets for common operations:

```bash
# Show available targets
make

# Run the server with default settings
make mcp-run

# Run with specific arguments
make mcp-run ARGS="--debug --config /path/to/config.yaml"

# Run with the inspector
make mcp-dev ARGS="--debug"
```

## Environment Variables

The server also supports configuration through environment variables:

```bash
# Set log level
export MCP_TS_LOG_LEVEL=DEBUG

# Set configuration file path
export MCP_TS_CONFIG_PATH=/path/to/config.yaml

# Run the server
mcp-server-tree-sitter
```

See the [Configuration Guide](./config.md) for more details on environment variables and configuration options.
