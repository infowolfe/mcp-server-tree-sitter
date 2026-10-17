"""Tests for config-driven service transport settings and the Click entry point."""

import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from mcp_server_tree_sitter.config import ConfigurationManager, ServerConfig, update_config_from_new
from mcp_server_tree_sitter.server import (
    _acquire_unix_socket_lock,
    _prepare_unix_socket,
    apply_service_settings,
    listen,
    main,
    mcp,
)


def _isolate_config(monkeypatch, tmp_path):
    """Keep the test off the user's config file and service environment."""
    monkeypatch.setenv("MCP_TS_CONFIG_PATH", str(tmp_path / "missing.yaml"))
    for key in list(os.environ):
        if key.startswith("MCP_TS_SERVICE"):
            monkeypatch.delenv(key, raising=False)


def _write_service_yaml(tmp_path, body):
    path = tmp_path / "config.yaml"
    path.write_text(body)
    return path


def test_yaml_loads_service_section(tmp_path, monkeypatch):
    """A service block in YAML reaches the live config, including the hand copy."""
    _isolate_config(monkeypatch, tmp_path)
    path = _write_service_yaml(
        tmp_path,
        "service:\n  transport: streamable-http\n  host: 127.0.0.1\n  port: 9001\n  mount_path: /ts\n",
    )

    manager = ConfigurationManager()
    manager.load_from_file(path)
    service = manager.get_config().service

    assert service.transport == "streamable-http"
    assert service.host == "127.0.0.1"
    assert service.port == 9001
    assert service.mount_path == "/ts"
    assert service.server is False
    assert service.socket is None
    assert manager.to_dict()["service"]["port"] == 9001
    assert manager.to_dict()["service"]["server"] is False


def test_service_defaults():
    """The process stays on stdio unless the file or the environment says otherwise."""
    service = ServerConfig().service
    assert service.transport == "stdio"
    assert service.server is False
    assert service.socket is None
    assert service.host == "127.0.0.1"
    assert service.port == 8765
    assert service.mount_path == "/mcp"


def test_env_overrides_yaml_service(tmp_path, monkeypatch):
    """MCP_TS_SERVICE_* wins over the YAML service section."""
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("MCP_TS_SERVICE_PORT", "9200")
    monkeypatch.setenv("MCP_TS_SERVICE__MOUNT_PATH", "/env")
    monkeypatch.setenv("MCP_TS_SERVICE_SERVER", "true")
    monkeypatch.setenv("MCP_TS_SERVICE_SOCKET", "/tmp/tree.sock")
    path = _write_service_yaml(
        tmp_path,
        "service:\n  transport: streamable-http\n  port: 9001\n  mount_path: /yaml\n",
    )

    manager = ConfigurationManager()
    manager.load_from_file(path)
    service = manager.get_config().service

    assert service.port == 9200
    assert service.mount_path == "/env"
    assert service.transport == "streamable-http"
    assert service.server is True
    assert service.socket == "/tmp/tree.sock"


def test_invalid_transport_rejected():
    """YAML construction rejects a transport the server cannot run."""
    with pytest.raises(ValidationError):
        ServerConfig(service={"transport": "websocket"})


def test_update_config_from_new_copies_service():
    """Reloading a file copies the service section instead of dropping it."""
    original = ServerConfig()
    new = ServerConfig(
        service={
            "server": True,
            "transport": "sse",
            "host": "0.0.0.0",
            "port": 9002,
            "mount_path": "/mcp",
            "socket": "/tmp/tree.sock",
        }
    )

    update_config_from_new(original, new)

    assert original.service is not new.service
    new.service.server = False
    assert original.service.server is True
    assert original.service.transport == "sse"
    assert original.service.host == "0.0.0.0"
    assert original.service.port == 9002
    assert original.service.mount_path == "/mcp"
    assert original.service.socket == "/tmp/tree.sock"


def test_apply_service_settings_stdio_leaves_listener_alone():
    """stdio does not write host, port, or the HTTP route onto the server."""
    server = SimpleNamespace(settings=SimpleNamespace(host="127.0.0.1", port=8000, streamable_http_path="/mcp"))

    selected = apply_service_settings(server, ServerConfig().service)

    assert selected == "stdio"
    assert server.settings.port == 8000
    assert server.settings.streamable_http_path == "/mcp"


def test_apply_service_settings_streamable_http_uses_mount_path_as_route():
    """mount_path becomes the streamable HTTP route and the listen address."""
    allowlist = object()
    server = SimpleNamespace(
        settings=SimpleNamespace(
            host="127.0.0.1",
            port=8000,
            streamable_http_path="/mcp",
            transport_security=allowlist,
        )
    )
    service = ServerConfig(
        service={
            "server": True,
            "transport": "streamable-http",
            "host": "0.0.0.0",
            "port": 8765,
            "mount_path": "/ts",
        }
    ).service

    selected = apply_service_settings(server, service)

    assert selected == "streamable-http"
    assert server.settings.host == "0.0.0.0"
    assert server.settings.port == 8765
    assert server.settings.streamable_http_path == "/ts"
    assert server.settings.transport_security is None


def test_apply_service_settings_loopback_keeps_host_allowlist():
    """A loopback host keeps the allowlist FastMCP installed at construction."""
    allowlist = object()
    server = SimpleNamespace(
        settings=SimpleNamespace(
            host="127.0.0.1",
            port=8000,
            streamable_http_path="/mcp",
            transport_security=allowlist,
        )
    )
    service = ServerConfig(
        service={"server": True, "transport": "streamable-http", "host": "localhost", "port": 8765}
    ).service

    apply_service_settings(server, service)

    assert server.settings.host == "localhost"
    assert server.settings.transport_security is allowlist


def test_apply_service_settings_sse_does_not_rewrite_streamable_route():
    """SSE sets the listen address and leaves the streamable HTTP route alone."""
    server = SimpleNamespace(settings=SimpleNamespace(host="127.0.0.1", port=8000, streamable_http_path="/mcp"))
    service = ServerConfig(service={"server": True, "transport": "sse", "port": 9002}).service

    selected = apply_service_settings(server, service)

    assert selected == "sse"
    assert server.settings.port == 9002
    assert server.settings.streamable_http_path == "/mcp"


def test_apply_service_settings_rejects_unknown_transport():
    """A transport that bypassed model validation fails before the server listens."""
    server = SimpleNamespace(settings=SimpleNamespace(host="127.0.0.1", port=8000, streamable_http_path="/mcp"))
    service = ServerConfig().service
    service.transport = "websocket"  # type: ignore[assignment]

    with pytest.raises(ValueError, match="websocket"):
        apply_service_settings(server, service)

    assert server.settings.port == 8000


def _invoke(monkeypatch, tmp_path, args, yaml_text, env=None):
    """Run the Click entry point against an isolated config manager."""
    _isolate_config(monkeypatch, tmp_path)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    path = _write_service_yaml(tmp_path, yaml_text)
    manager = ConfigurationManager()
    container = Mock()
    container.config_manager = manager
    container.get_config.side_effect = manager.get_config
    container.tree_cache = Mock()
    container.content_cache = Mock()
    saved = (
        mcp.settings.host,
        mcp.settings.port,
        mcp.settings.streamable_http_path,
        mcp.settings.transport_security,
    )
    try:
        with (
            patch("mcp_server_tree_sitter.server.get_container", return_value=container),
            patch("mcp_server_tree_sitter.capabilities.register_capabilities"),
            patch("mcp_server_tree_sitter.tools.registration.register_tools"),
            patch.object(mcp, "run") as run,
        ):
            result = CliRunner().invoke(main, ["--config", str(path), *args])
        return result, manager, run
    finally:
        (
            mcp.settings.host,
            mcp.settings.port,
            mcp.settings.streamable_http_path,
            mcp.settings.transport_security,
        ) = saved


_HTTP_YAML = (
    "service:\n  server: true\n  transport: streamable-http\n  host: 127.0.0.1\n  port: 9001\n  mount_path: /ts\n"
)


def test_omitted_cli_flag_keeps_yaml_port(tmp_path, monkeypatch):
    """An omitted --port leaves the YAML port in place."""
    result, manager, run = _invoke(monkeypatch, tmp_path, [], _HTTP_YAML)

    assert result.exit_code == 0, result.output
    assert manager.get_config().service.port == 9001
    run.assert_called_once_with(transport="streamable-http")


def test_explicit_port_overrides_yaml_when_env_is_unset(tmp_path, monkeypatch):
    """--port replaces the YAML port when no service environment variable is set."""
    result, manager, run = _invoke(monkeypatch, tmp_path, ["--port", "9100"], _HTTP_YAML)

    assert result.exit_code == 0, result.output
    assert manager.get_config().service.port == 9100
    assert manager.get_config().service.mount_path == "/ts"
    run.assert_called_once_with(transport="streamable-http")


def test_env_wins_over_explicit_port(tmp_path, monkeypatch):
    """MCP_TS_SERVICE_PORT still wins after an explicit --port."""
    result, manager, _run = _invoke(
        monkeypatch,
        tmp_path,
        ["--port", "9100"],
        _HTTP_YAML,
        env={"MCP_TS_SERVICE_PORT": "9200"},
    )

    assert result.exit_code == 0, result.output
    assert manager.get_config().service.port == 9200


def test_non_loopback_cli_host_clears_allowlist_only_for_that_run(tmp_path, monkeypatch):
    """--host outside loopback clears the allowlist, and the helper puts it back."""
    original = mcp.settings.transport_security
    sentinel = object()
    mcp.settings.transport_security = sentinel
    seen: list[object] = []

    def spy(server, service):
        selected = apply_service_settings(server, service)
        seen.append(server.settings.transport_security)
        return selected

    try:
        with patch("mcp_server_tree_sitter.server.apply_service_settings", side_effect=spy):
            result, manager, run = _invoke(monkeypatch, tmp_path, ["--host", "0.0.0.0"], _HTTP_YAML)

        assert result.exit_code == 0, result.output
        assert manager.get_config().service.host == "0.0.0.0"
        assert seen == [None]
        assert mcp.settings.transport_security is sentinel
        run.assert_called_once_with(transport="streamable-http")
    finally:
        mcp.settings.transport_security = original


def test_http_transport_without_server_stays_on_stdio():
    """A listen transport does nothing until server is set."""
    server = SimpleNamespace(settings=SimpleNamespace(host="127.0.0.1", port=8000, streamable_http_path="/mcp"))
    service = ServerConfig(service={"transport": "streamable-http", "port": 9001}).service

    selected = apply_service_settings(server, service)

    assert selected == "stdio"
    assert server.settings.port == 8000


def test_server_flag_promotes_default_transport_to_streamable_http():
    """server true with transport stdio listens on the streamable HTTP route."""
    server = SimpleNamespace(
        settings=SimpleNamespace(
            host="127.0.0.1",
            port=8000,
            streamable_http_path="/other",
            transport_security=object(),
        )
    )
    service = ServerConfig(service={"server": True}).service

    selected = apply_service_settings(server, service)

    assert selected == "streamable-http"
    assert server.settings.port == 8765
    assert server.settings.streamable_http_path == "/mcp"


def test_unix_socket_does_not_rewrite_the_tcp_bind():
    """A socket path clears the Host allowlist and leaves host and port alone."""
    allowlist = object()
    server = SimpleNamespace(
        settings=SimpleNamespace(
            host="127.0.0.1",
            port=8000,
            streamable_http_path="/mcp",
            transport_security=allowlist,
        )
    )
    service = ServerConfig(
        service={"server": True, "socket": "/tmp/tree.sock", "host": "0.0.0.0", "port": 9001}
    ).service

    selected = apply_service_settings(server, service)

    assert selected == "streamable-http"
    assert server.settings.host == "127.0.0.1"
    assert server.settings.port == 8000
    assert server.settings.transport_security is None


def test_listen_binds_a_unix_socket_with_uvicorn(tmp_path):
    """Persistent mode with a socket path does not call FastMCP.run."""
    sock = tmp_path / "tree.sock"
    app = object()
    server = Mock()
    server.settings = SimpleNamespace(
        host="127.0.0.1",
        port=8000,
        streamable_http_path="/mcp",
        transport_security=object(),
        log_level="INFO",
    )
    server.streamable_http_app.return_value = app
    service = ServerConfig(service={"server": True, "socket": str(sock)}).service

    with patch("uvicorn.run") as uv_run:
        listen(server, service)

    server.run.assert_not_called()
    server.streamable_http_app.assert_called_once_with()
    uv_run.assert_called_once_with(app, uds=str(sock), log_level="info")


def test_listen_uses_sse_app_for_an_sse_socket(tmp_path):
    """An SSE server on a Unix socket builds the SSE app."""
    app = object()
    server = Mock()
    server.settings = SimpleNamespace(
        host="127.0.0.1",
        port=8000,
        streamable_http_path="/mcp",
        transport_security=object(),
        log_level="WARNING",
    )
    server.sse_app.return_value = app
    service = ServerConfig(service={"server": True, "transport": "sse", "socket": str(tmp_path / "sse.sock")}).service

    with patch("uvicorn.run") as uv_run:
        listen(server, service)

    server.sse_app.assert_called_once_with()
    server.streamable_http_app.assert_not_called()
    uv_run.assert_called_once_with(app, uds=str(tmp_path / "sse.sock"), log_level="warning")


def test_prepare_unix_socket_replaces_a_stale_socket(tmp_path):
    """A leftover socket file is removed so the next bind can succeed."""
    import socket

    path = tmp_path / "old.sock"
    raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    raw.bind(str(path))
    raw.close()

    _prepare_unix_socket(str(path))

    assert not path.exists()


def test_prepare_unix_socket_refuses_a_live_listener(tmp_path):
    """A socket another process is accepting on is left in place."""
    import socket

    path = tmp_path / "live.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(5)
    try:
        with pytest.raises(ValueError, match="already in use"):
            _prepare_unix_socket(str(path))

        assert path.is_socket()
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(1)
        client.connect(str(path))
        client.close()
    finally:
        listener.close()


def test_unix_socket_lock_refuses_a_second_holder(tmp_path):
    """A second open of the lock file cannot take the exclusive lock."""
    path = tmp_path / "tree.sock"
    first = _acquire_unix_socket_lock(str(path))
    try:
        with pytest.raises(ValueError, match="already in use"):
            _acquire_unix_socket_lock(str(path))
        assert os.path.isfile(f"{path}.lock")
    finally:
        os.close(first)

    second = _acquire_unix_socket_lock(str(path))
    os.close(second)


def test_listen_holds_the_socket_lock_while_serving(tmp_path):
    """The lock is still held when uvicorn is entered, and released after it returns."""
    sock = tmp_path / "tree.sock"
    app = object()
    server = Mock()
    server.settings = SimpleNamespace(
        host="127.0.0.1",
        port=8000,
        streamable_http_path="/mcp",
        transport_security=object(),
        log_level="INFO",
    )
    server.streamable_http_app.return_value = app
    service = ServerConfig(service={"server": True, "socket": str(sock)}).service

    def uv_run(*_args, **_kwargs):
        with pytest.raises(ValueError, match="already in use"):
            _acquire_unix_socket_lock(str(sock))

    with patch("uvicorn.run", side_effect=uv_run):
        listen(server, service)

    released = _acquire_unix_socket_lock(str(sock))
    os.close(released)


def test_listen_refuses_a_missing_socket_directory_without_a_lock_file(tmp_path):
    """A missing directory is reported before a lock file is created."""
    missing = tmp_path / "missing" / "tree.sock"
    server = Mock()
    server.settings = SimpleNamespace(log_level="INFO", transport_security=object())
    service = ServerConfig(service={"server": True, "socket": str(missing)}).service

    with pytest.raises(ValueError, match="does not exist"):
        listen(server, service)

    assert not (tmp_path / "missing").exists()
    server.streamable_http_app.assert_not_called()


def test_listen_refuses_a_regular_file_without_leaving_a_lock(tmp_path):
    """A non-socket path is left unchanged and does not gain a lock file."""
    path = tmp_path / "not-a-socket"
    path.write_text("nope")
    server = Mock()
    server.settings = SimpleNamespace(log_level="INFO", transport_security=object())
    service = ServerConfig(service={"server": True, "socket": str(path)}).service

    with pytest.raises(ValueError, match="not a socket"):
        listen(server, service)

    assert path.read_text() == "nope"
    assert not os.path.exists(f"{path}.lock")


def test_prepare_unix_socket_refuses_a_regular_file(tmp_path):
    """A path that is not a socket is left in place and reported."""
    path = tmp_path / "not-a-socket"
    path.write_text("nope")

    with pytest.raises(ValueError, match="not a socket"):
        _prepare_unix_socket(str(path))

    assert path.read_text() == "nope"


def test_prepare_unix_socket_requires_the_directory(tmp_path):
    """The parent directory has to exist before uvicorn binds."""
    missing = tmp_path / "missing" / "tree.sock"

    with pytest.raises(ValueError, match="does not exist"):
        _prepare_unix_socket(str(missing))


def test_omitted_server_keeps_http_yaml_on_stdio(tmp_path, monkeypatch):
    """transport streamable-http does not listen unless server is set."""
    yaml_text = "service:\n  transport: streamable-http\n  port: 9001\n"
    result, manager, run = _invoke(monkeypatch, tmp_path, [], yaml_text)

    assert result.exit_code == 0, result.output
    assert manager.get_config().service.server is False
    run.assert_called_once_with()


def test_server_flag_listens_with_streamable_http(tmp_path, monkeypatch):
    """--server turns a default stdio config into a streamable HTTP listener."""
    result, manager, run = _invoke(monkeypatch, tmp_path, ["--server"], "service:\n  port: 9001\n")

    assert result.exit_code == 0, result.output
    assert manager.get_config().service.server is True
    assert manager.get_config().service.transport == "stdio"
    run.assert_called_once_with(transport="streamable-http")


def test_no_server_overrides_yaml(tmp_path, monkeypatch):
    """--no-server keeps the process on stdio when the file says server true."""
    result, manager, run = _invoke(monkeypatch, tmp_path, ["--no-server"], _HTTP_YAML)

    assert result.exit_code == 0, result.output
    assert manager.get_config().service.server is False
    run.assert_called_once_with()


def test_env_wins_over_server_flag(tmp_path, monkeypatch):
    """MCP_TS_SERVICE_SERVER still wins after an explicit --server."""
    result, manager, run = _invoke(
        monkeypatch,
        tmp_path,
        ["--server"],
        _HTTP_YAML,
        env={"MCP_TS_SERVICE_SERVER": "false"},
    )

    assert result.exit_code == 0, result.output
    assert manager.get_config().service.server is False
    run.assert_called_once_with()


def test_socket_flag_uses_uvicorn(tmp_path, monkeypatch):
    """--socket with --server binds that path and does not call FastMCP.run."""
    sock = tmp_path / "cli.sock"
    app = object()
    with (
        patch("uvicorn.run") as uv_run,
        patch.object(mcp, "streamable_http_app", return_value=app),
    ):
        result, manager, run = _invoke(
            monkeypatch,
            tmp_path,
            ["--server", "--socket", str(sock)],
            "log_level: INFO\n",
        )

    assert result.exit_code == 0, result.output
    assert manager.get_config().service.socket == str(sock)
    run.assert_not_called()
    uv_run.assert_called_once_with(app, uds=str(sock), log_level="info")


def test_version_flag_does_not_start_server():
    """--version prints the version and does not call mcp.run."""
    with patch.object(mcp, "run") as run:
        result = CliRunner().invoke(main, ["--version"])

    assert result.exit_code == 0
    assert "mcp-server-tree-sitter version" in result.output
    run.assert_not_called()
