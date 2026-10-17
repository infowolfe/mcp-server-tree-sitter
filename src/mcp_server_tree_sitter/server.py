"""MCP server implementation for Tree-sitter with dependency injection."""

import os
import socket
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import click
from mcp.server.fastmcp import FastMCP

from .bootstrap import get_logger, update_log_levels
from .config import ServerConfig, ServiceConfig
from .di import DependencyContainer, get_container

# Create server instance
mcp = FastMCP("tree_sitter")

# Set up logger
logger = get_logger(__name__)


def configure_with_context(
    container: DependencyContainer,
    config_path: Optional[str] = None,
    cache_enabled: Optional[bool] = None,
    max_file_size_mb: Optional[int] = None,
    log_level: Optional[str] = None,
) -> Tuple[Dict[str, Any], ServerConfig]:
    """Configure the server with explicit context.

    Args:
        container: DependencyContainer instance
        config_path: Path to YAML config file
        cache_enabled: Whether to enable parse tree caching
        max_file_size_mb: Maximum file size in MB
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)

    Returns:
        Tuple of (configuration dict, ServerConfig object)
    """
    # Get initial config for comparison
    config_manager = container.config_manager
    tree_cache = container.tree_cache
    initial_config = config_manager.get_config()
    logger.info(
        f"Initial configuration: "
        f"cache.max_size_mb = {initial_config.cache.max_size_mb}, "
        f"security.max_file_size_mb = {initial_config.security.max_file_size_mb}, "
        f"language.default_max_depth = {initial_config.language.default_max_depth}"
    )

    # Load config if path provided
    if config_path:
        logger.info(f"Configuring server with YAML config from: {config_path}")
        # Log absolute path to ensure we're looking at the right file
        abs_path = os.path.abspath(config_path)
        logger.info(f"Absolute path: {abs_path}")

        # Check if the file exists before trying to load it
        if not os.path.exists(abs_path):
            logger.error(f"Config file does not exist: {abs_path}")

        config_manager.load_from_file(abs_path)

        # Log configuration after loading YAML
        intermediate_config = config_manager.get_config()
        logger.info(
            f"Configuration after loading YAML: "
            f"cache.max_size_mb = {intermediate_config.cache.max_size_mb}, "
            f"security.max_file_size_mb = {intermediate_config.security.max_file_size_mb}, "
            f"language.default_max_depth = {intermediate_config.language.default_max_depth}"
        )

    # Update specific settings if provided
    if cache_enabled is not None:
        logger.info(f"Setting cache.enabled to {cache_enabled}")
        config_manager.update_value("cache.enabled", cache_enabled)
        tree_cache.set_enabled(cache_enabled)
        container.content_cache.set_enabled(cache_enabled)

    if max_file_size_mb is not None:
        logger.info(f"Setting security.max_file_size_mb to {max_file_size_mb}")
        config_manager.update_value("security.max_file_size_mb", max_file_size_mb)

    if log_level is not None:
        logger.info(f"Setting log_level to {log_level}")
        config_manager.update_value("log_level", log_level)

        # Apply log level using already imported update_log_levels
        update_log_levels(log_level)
        logger.debug(f"Applied log level {log_level} to mcp_server_tree_sitter loggers")

    # Get final configuration
    config = config_manager.get_config()
    logger.info(
        f"Final configuration: "
        f"cache.max_size_mb = {config.cache.max_size_mb}, "
        f"security.max_file_size_mb = {config.security.max_file_size_mb}, "
        f"language.default_max_depth = {config.language.default_max_depth}"
    )

    # Return current config as dict and the actual config object
    config_dict = config_manager.to_dict()
    return config_dict, config


_SERVICE_TRANSPORTS = ("stdio", "sse", "streamable-http")
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def apply_service_settings(server: FastMCP, service: ServiceConfig) -> str:
    """Apply ``service`` to ``server`` and return the transport to run.

    ``server`` false always returns ``stdio`` and leaves the listener alone.
    ``server`` true with transport ``stdio`` listens as ``streamable-http``.

    Host, port, and the streamable HTTP route are written onto FastMCP
    settings. MCP 2 passes those as ``run()`` arguments and drops
    ``settings.port``, so this is the only function that touches them.
    A Unix socket does not use host or port. ``listen`` binds it with uvicorn
    because FastMCP's ``run`` has no socket argument.

    ``mount_path`` is the streamable HTTP route. SSE keeps the SDK listen
    paths. ``settings.mount_path`` only rewrites the advertised SSE message
    URL, so it is left unchanged.

    FastMCP installs a loopback Host allowlist when it is constructed with
    the default host. Changing ``settings.host`` later does not rebuild that
    allowlist, so a non-loopback bind would listen and then answer 421.
    Clearing ``transport_security`` matches constructing FastMCP with that host.
    A Unix socket has no Host allowlist either: the directory permissions are
    the access check, and uvicorn creates the socket as mode 0666.
    """
    transport = service.transport
    if transport not in _SERVICE_TRANSPORTS:
        allowed = ", ".join(_SERVICE_TRANSPORTS)
        msg = f"Unknown service transport {transport!r}. Expected one of: {allowed}"
        raise ValueError(msg)
    if not service.server:
        return "stdio"
    selected = "streamable-http" if transport == "stdio" else transport
    if service.socket:
        server.settings.transport_security = None
    else:
        server.settings.host = service.host
        server.settings.port = service.port
        if service.host not in _LOOPBACK_HOSTS:
            server.settings.transport_security = None
    if selected == "streamable-http":
        server.settings.streamable_http_path = service.mount_path
    return selected


def _unix_socket_is_listening(path: Path) -> bool:
    """Return whether a process is accepting connections on ``path``.

    A refused connection means the file is leftover. Any other failure is
    treated as in use so this process does not delete a socket it could not
    prove is stale.
    """
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(1.0)
        probe.connect(os.fspath(path))
    except ConnectionRefusedError:
        return False
    except FileNotFoundError:
        return False
    except OSError:
        return True
    else:
        return True
    finally:
        probe.close()


def _acquire_unix_socket_lock(path: str) -> int:
    """Hold an exclusive lock until the caller closes the returned descriptor.

    The lock file stays on disk. Removing it would let another process lock a
    different inode while this process still holds the old one.

    ``fcntl`` is imported here because this module is also the stdio entry
    point, and Windows does not provide that module.
    """
    import fcntl

    fd = os.open(f"{path}.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        msg = f"Unix socket is already in use: {path}"
        raise ValueError(msg) from None
    return fd


def _check_unix_socket_path(path: str) -> Path:
    """Reject a missing directory or a path that is not a socket."""
    sock_path = Path(path)
    parent = sock_path.parent
    if not parent.is_dir():
        msg = f"Unix socket directory does not exist: {parent}"
        raise ValueError(msg)
    if sock_path.exists() and not sock_path.is_socket():
        msg = f"Unix socket path exists and is not a socket: {sock_path}"
        raise ValueError(msg)
    return sock_path


def _prepare_unix_socket(path: str) -> None:
    """Remove a stale socket so uvicorn can bind this path.

    A socket another process is still accepting on is left in place.
    """
    sock_path = _check_unix_socket_path(path)
    if not sock_path.exists():
        return
    if _unix_socket_is_listening(sock_path):
        msg = f"Unix socket is already in use: {sock_path}"
        raise ValueError(msg)
    try:
        sock_path.unlink()
    except FileNotFoundError:
        return


def listen(server: FastMCP, service: ServiceConfig) -> None:
    """Run stdio, or listen on TCP or a Unix socket."""
    selected = apply_service_settings(server, service)
    logger.info("Starting MCP Tree-sitter Server")
    if selected == "stdio":
        server.run()
        return
    if not service.socket:
        if selected == "sse":
            server.run(transport="sse")
        else:
            server.run(transport="streamable-http")
        return

    import uvicorn

    # Validate before the lock file is created. A missing directory or a
    # regular file must not leave ``{path}.lock`` behind.
    _check_unix_socket_path(service.socket)
    app = server.sse_app() if selected == "sse" else server.streamable_http_app()
    # Hold this across uvicorn.run. Its bind goes through create_unix_server,
    # which removes any socket already at the path, and its shutdown removes
    # the path again. The lock stops a second process from reaching that bind.
    lock_fd = _acquire_unix_socket_lock(service.socket)
    try:
        _prepare_unix_socket(service.socket)
        uvicorn.run(app, uds=service.socket, log_level=server.settings.log_level.lower())
    finally:
        os.close(lock_fd)


def _print_version() -> None:
    """Print the distribution version and return."""
    import importlib.metadata

    try:
        version = importlib.metadata.version("tree-sitter-mcp-ng")
    except importlib.metadata.PackageNotFoundError:
        print("mcp-server-tree-sitter (version unknown - package not installed)")
    else:
        print(f"mcp-server-tree-sitter version {version}")


@click.command(
    name="mcp-server-tree-sitter",
    help="MCP Tree-sitter Server - Code analysis with tree-sitter",
)
@click.option("--config", "config_path", default=None, help="Path to configuration file")
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.option("--disable-cache", is_flag=True, help="Disable parse tree caching")
@click.option("--version", is_flag=True, help="Show version and exit")
@click.option(
    "--transport",
    default=None,
    type=click.Choice(list(_SERVICE_TRANSPORTS)),
    help="Transport to serve. Overrides the config file only when passed.",
)
@click.option("--host", default=None, help="HTTP listen address. Overrides the config file only when passed.")
@click.option("--port", default=None, type=int, help="HTTP listen port. Overrides the config file only when passed.")
@click.option(
    "--mount-path",
    "mount_path",
    default=None,
    help="Streamable HTTP route. Overrides the config file only when passed.",
)
@click.option(
    "--server/--no-server",
    "server",
    default=None,
    help="Listen persistently. Overrides the config file only when passed.",
)
@click.option(
    "--socket",
    default=None,
    help="Unix socket path. Replaces host and port. Overrides the config file only when passed.",
)
def main(
    config_path: str | None,
    debug: bool,
    disable_cache: bool,
    version: bool,
    transport: str | None,
    host: str | None,
    port: int | None,
    mount_path: str | None,
    server: bool | None,
    socket: str | None,
) -> None:
    """Run the server with command-line argument handling."""
    if version:
        _print_version()
        sys.exit(0)

    # Set up debug logging if requested
    if debug:
        # Set environment variable first for consistency
        os.environ["MCP_TS_LOG_LEVEL"] = "DEBUG"
        # Then update log levels
        update_log_levels("DEBUG")
        logger.debug("Debug logging enabled")

    # Get the container
    container = get_container()

    # Configure with provided options
    if config_path:
        logger.info(f"Loading configuration from {config_path}")
        container.config_manager.load_from_file(config_path)

    if disable_cache:
        logger.info("Disabling parse tree cache as requested")
        container.config_manager.update_value("cache.enabled", False)
        container.tree_cache.set_enabled(False)
        container.content_cache.set_enabled(False)

    # CLI flags override the file only when explicitly passed.
    # update_value reapplies environment variables, so MCP_TS_SERVICE_* still wins.
    if transport is not None:
        container.config_manager.update_value("service.transport", transport)
    if host is not None:
        container.config_manager.update_value("service.host", host)
    if port is not None:
        container.config_manager.update_value("service.port", port)
    if mount_path is not None:
        container.config_manager.update_value("service.mount_path", mount_path)
    if server is not None:
        container.config_manager.update_value("service.server", server)
    if socket is not None:
        container.config_manager.update_value("service.socket", socket)

    # Register capabilities and tools
    from .capabilities import register_capabilities
    from .tools.registration import register_tools

    register_capabilities(mcp)
    register_tools(mcp, container)

    # Load configuration from environment
    config = container.get_config()

    # Update tree cache settings from config
    container.tree_cache.set_max_size_mb(config.cache.max_size_mb)
    container.tree_cache.set_enabled(config.cache.enabled)
    container.content_cache.set_enabled(config.cache.enabled)

    listen(mcp, config.service)


if __name__ == "__main__":
    main()
