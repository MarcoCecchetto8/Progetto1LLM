import asyncio
from datetime import UTC, datetime

from fastmcp import Client

from lab_server.server import create_server

FIXED = lambda: datetime(2026, 10, 26, 13, 32, 5, tzinfo=UTC)


def call(server, action):
    """Esegue action(client) con un client MCP in memoria collegato al server."""
    async def main():
        async with Client(server) as client:
            return await action(client)
    return asyncio.run(main())


def server():
    return create_server("Europe/Rome", FIXED)


def test_catalog_lists_clock():
    tools = {t.name: t for t in call(server(), lambda c: c.list_tools())}
    assert "get_current_time" in tools
    assert "timezone" in tools["get_current_time"].inputSchema["properties"]
    assert tools["get_current_time"].description


def test_clock_call():
    result = call(server(), lambda c: c.call_tool("get_current_time", {"timezone": "Asia/Tokyo"}))
    assert result.content[0].text == "Asia/Tokyo: 2026-10-26T22:32:05+09:00"


def test_clock_unknown_timezone_is_error():
    result = call(server(), lambda c: c.call_tool("get_current_time", {"timezone": "Marte/Base"}, raise_on_error=False))
    assert result.is_error is True
    assert result.content[0].text == 'Fuso orario sconosciuto: "Marte/Base". Usa un nome IANA, es. Europe/Rome.'
