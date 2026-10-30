"""Avvia l'agente AI in locale e dialoga con il server MCP via stdio."""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

from agent import JsonlLogger, OllamaProvider, run_agent
from database import init_db, statistiche


def confirm_write(question: str) -> bool:
    print("\n" + question)
    answer = input("Confermi? Scrivi SI per procedere: ").strip().upper()
    return answer == "SI"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Asteria Store Agent - assistente locale")
    parser.add_argument("--model", default="qwen3:4b", help="Nome modello scaricato con Ollama")
    parser.add_argument("--url", default="http://127.0.0.1:11434", help="Indirizzo locale di Ollama")
    args = parser.parse_args()
    init_db()
    dati = statistiche()
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).with_name("mcp_server.py"))],
        env=os.environ.copy(),
    )
    provider = OllamaProvider(model=args.model, base_url=args.url)
    logger = JsonlLogger()
    history = []  # Memoria conversazionale delle ultime 6 coppie domanda/risposta
    print("\nAsteria Store Agent - assistente locale")
    print(f"Catalogo: {dati['prodotti']} prodotti | {dati['clienti_sintetici']} clienti fittizi | {dati['ordini']} ordini")
    print(f"Modello: {args.model} | Scrivi 'esci' per terminare")
    print("Esempi: 'Che prodotti avete?', 'Cerca una tastiera', 'Mostra ordine 1001'\n")
    try:
        async with Client(params) as client:
            listed = await client.list_tools()
            print("Server MCP collegato. Tool:", ", ".join(t.name for t in listed.tools))
            while True:
                try:
                    request = input("\nTu > ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if request.lower() in ("esci", "exit", "quit"):
                    break
                if not request:
                    continue
                answer = await run_agent(client, request, provider, logger,
                                         confirm_write, history=history)
                print("\nAgente >", answer)
    except Exception as exc:
        print("\nErrore di collegamento MCP:", exc)
        print("Prima esegui 'python test_mcp.py' per controllare il server.")
        raise SystemExit(1) from None
    print("\nChiuso. Per analizzare i token esegui: python token_report.py")


if __name__ == "__main__":
    asyncio.run(main())
