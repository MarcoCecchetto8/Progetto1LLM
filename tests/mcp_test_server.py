"""Server MCP di prova per i test del client: python -m tests.mcp_test_server."""

import os

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

mcp = FastMCP("Prova")


@mcp.tool
def echo(text: str) -> str:
    """Restituisce il testo ricevuto."""
    return text


@mcp.tool
def fail() -> str:
    """Restituisce sempre un errore dello strumento."""
    raise ToolError("errore di prova")


@mcp.tool
def die() -> str:
    """Termina il processo del server, come un crash."""
    os._exit(3)


if __name__ == "__main__":
    mcp.run(show_banner=False)
