"""Verifica diretta del server, senza assistente e senza modello.

python -m lab_server.check                         → catalogo (nome, descrizione, schema)
python -m lab_server.check <tool> chiave=valore    → invoca il tool e stampa il risultato
"""

import asyncio
import json
import os
import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


def parse_args(items: list[str]) -> dict[str, object]:
    arguments = {}
    for item in items:
        key, sep, raw = item.partition("=")
        if not sep or not key:
            raise SystemExit(f"Argomento non valido: '{item}'. Usa chiave=valore, es. timezone=Asia/Tokyo.")
        try:
            # 2.5 → numero, true → booleano; il resto (es. Asia/Tokyo) resta testo
            arguments[key] = json.loads(raw)
        except json.JSONDecodeError:
            arguments[key] = raw
    return arguments


async def check(argv: list[str]) -> int:
    env = {**os.environ, "FASTMCP_LOG_LEVEL": os.environ.get("FASTMCP_LOG_LEVEL", "CRITICAL")}
    # Stesso avvio dell'assistente: il server parte come sottoprocesso e si parla in stdio
    transport = StdioTransport(sys.executable, ["-m", "lab_server"], env=env)
    async with Client(transport) as client:
        if not argv:
            for tool in await client.list_tools():
                print(f"{tool.name}: {tool.description}")
                print(json.dumps(tool.inputSchema, ensure_ascii=False, indent=2))
            return 0
        result = await client.call_tool(argv[0], parse_args(argv[1:]), raise_on_error=False)
        text = "\n".join(block.text for block in result.content if block.type == "text")
        if result.is_error:
            print(f"ERRORE: {text}")
            return 1
        print(text)
        return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    return asyncio.run(check(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
