"""Bitbucket MCP Server - Container optimized MCP server for Bitbucket API"""

try:
    from importlib.metadata import version, PackageNotFoundError
    __version__ = version("bitbucket-mcp-py")
except PackageNotFoundError:
    __version__ = "unknown"
