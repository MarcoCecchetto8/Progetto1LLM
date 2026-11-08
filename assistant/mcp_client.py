"""Client MCP: avvia il server in stdio, legge il catalogo e offre tool LangChain sincroni."""

import asyncio
import os
import sys
import threading
from collections.abc import Mapping
from concurrent.futures import Future

from langchain_core.tools import BaseTool, StructuredTool, ToolException
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from assistant.config import Settings


class MCPConnectionError(Exception):
    """Server degli strumenti non avviabile, terminato o senza risposta (non un errore dello strumento)."""


def server_command() -> list[str]:
    return [sys.executable, "-m", "lab_server"]


def server_env(settings: Settings) -> dict[str, str]:
    env = dict(os.environ)
    env["DEFAULT_TIMEZONE"] = settings.default_timezone
    env["LOG_LEVEL"] = settings.log_level
    # Senza DEBUG FastMCP non deve scrivere nel terminale le righe sugli errori degli strumenti
    env["FASTMCP_LOG_LEVEL"] = "DEBUG" if settings.log_level == "DEBUG" else "ERROR"
    return env


class MCPClient:
    """Una sola sessione MCP per tutta la durata del programma.

    Le librerie MCP sono asincrone: la sessione vive in un ciclo asyncio su un thread dedicato,
    e i tool restituiti lo usano in modo sincrono, così grafo e terminale restano sincroni.
    """

    def __init__(self, command: list[str], env: Mapping[str, str], errlog=None, timeout: float = 30.0):
        self.command = command
        self.env = dict(env)
        self.errlog = errlog
        self.timeout = timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop: asyncio.Event | None = None
        self._session: Future | None = None
        self._closed = False

    def __enter__(self) -> list[BaseTool]:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> list[BaseTool]:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="mcp-client", daemon=True)
        self._thread.start()
        ready: Future = Future()
        self._session = asyncio.run_coroutine_threadsafe(self._run(ready), self._loop)
        try:
            tools = ready.result(timeout=self.timeout)
        except Exception as error:
            self.close()
            detail = str(error) or type(error).__name__
            raise MCPConnectionError(
                f"Impossibile avviare il server degli strumenti ({' '.join(self.command)}): {detail}") from error
        return [self._sync_tool(tool) for tool in tools]

    async def _run(self, ready: Future) -> None:
        self._stop = asyncio.Event()
        params = StdioServerParameters(command=self.command[0], args=self.command[1:], env=self.env)
        try:
            async with stdio_client(params, errlog=self.errlog or sys.stderr) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    # handle_tool_errors=False: un errore del server diventa ToolException, non un risultato
                    ready.set_result(await load_mcp_tools(session, handle_tool_errors=False))
                    await self._stop.wait()
        except BaseException as error:
            if not ready.done():
                ready.set_exception(error)
            raise

    def _sync_tool(self, tool: BaseTool) -> BaseTool:
        def call(**arguments) -> str:
            if self._closed:
                raise MCPConnectionError("La sessione con il server degli strumenti è chiusa.")
            pending = asyncio.run_coroutine_threadsafe(tool.ainvoke(arguments), self._loop)
            try:
                content = pending.result(timeout=self.timeout)
            except ToolException as error:
                raise ToolException(str(error)) from None
            except Exception as error:
                pending.cancel()
                detail = str(error) or type(error).__name__
                raise MCPConnectionError(f"Il server degli strumenti non risponde: {detail}") from error
            if isinstance(content, str):
                return content
            return "\n".join(block["text"] for block in content if block.get("type") == "text")

        return StructuredTool(name=tool.name, description=tool.description, args_schema=tool.args_schema, func=call)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._loop is None:
            return
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._session is not None:
            try:
                self._session.result(timeout=5)
            except Exception:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
