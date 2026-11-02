"""Test di un guasto temporaneo: MCP e Ollama reali, errore iniettato una volta."""

import asyncio
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters
from agent import JsonlLogger, OllamaProvider, run_agent
from database import init_db


class ClientConGuasto:
    def __init__(self, client):
        self.client = client
        self.guasti = 0

    async def list_tools(self):
        return await self.client.list_tools()

    async def call_tool(self, name, arguments):
        if name == "verifica_disponibilita" and self.guasti == 0:
            self.guasti += 1
            print("[TEST] Errore di comunicazione simulato sul tool verifica_disponibilita.")
            raise RuntimeError("Guasto temporaneo simulato nella comunicazione con il tool")
        return await self.client.call_tool(name, arguments)


async def main():
    init_db()
    cartella = Path(__file__).resolve().parent
    log_path = cartella / "logs" / "prova_errore_tool.jsonl"
    logger = JsonlLogger(log_path)
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(cartella / "mcp_server.py")],
        env=os.environ.copy(),
    )
    print("Asteria Store - test di guasto controllato")
    print("Il server MCP e Qwen3 sono reali; soltanto il primo errore e' simulato.")
    richiesta = "Controlla con il tool verifica_disponibilita quante tastiere SKU-001 sono disponibili."
    print("Richiesta:", richiesta)
    async with Client(params) as client:
        wrapper = ClientConGuasto(client)
        risposta = await run_agent(
            wrapper,
            richiesta,
            OllamaProvider(model="qwen3:4b"),
            logger,
            confirm=lambda _: False,  # Nessun ordine puo' essere autorizzato.
        )
        print("\nRisposta dell'agente:", risposta)
        print("Guasti iniettati:", wrapper.guasti)
    print("ID richiesta:", logger.request_id)
    print("Log:", log_path)
    if wrapper.guasti == 0:
        print("ATTENZIONE: il modello non ha invocato verifica_disponibilita; ripetere la prova.")


if __name__ == "__main__":
    asyncio.run(main())
