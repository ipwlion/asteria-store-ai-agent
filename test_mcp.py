"""Controlla la comunicazione con il server MCP, senza usare Ollama."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters
from database import init_db


async def main():
    init_db()
    server = Path(__file__).with_name("mcp_server.py")
    params = StdioServerParameters(command=sys.executable, args=[str(server)])
    async with Client(params) as client:
        result = await client.list_tools()
        names = [tool.name for tool in result.tools]
        print("Tool MCP:", ", ".join(names))
        assert set(names) >= {"cerca_prodotti", "elenca_catalogo", "verifica_disponibilita", "consulta_ordine", "crea_ordine"}
        catalogo = await client.call_tool("elenca_catalogo", {})
        assert not catalogo.is_error, "Errore nella lettura del catalogo"
        stock = await client.call_tool("verifica_disponibilita", {"codice": "SKU-001"})
        assert not stock.is_error, "Errore nella chiamata MCP"
        data = stock.structured_content
        if data is None:
            data = [getattr(chunk, "text", "") for chunk in stock.content]
        print(json.dumps(data, indent=2, ensure_ascii=False))
    print("OK - Server MCP stdio verificato. Nessun hosting necessario.")


if __name__ == "__main__":
    asyncio.run(main())
