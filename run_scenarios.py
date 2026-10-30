import argparse
import asyncio
import csv
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from agent import JsonlLogger, LLMProvider, run_agent
from database import check_stock, create_order, get_order, init_db, list_catalog, search_products

BASE = Path(__file__).resolve().parent
SCHEMAS = {
    'cerca_prodotti': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']},
    'elenca_catalogo': {'type': 'object', 'properties': {'categoria': {'type': 'string'}, 'pagina': {'type': 'integer'}}},
    'verifica_disponibilita': {'type': 'object', 'properties': {'codice': {'type': 'string'}}, 'required': ['codice']},
    'consulta_ordine': {'type': 'object', 'properties': {'numero_ordine': {'type': 'integer'}}, 'required': ['numero_ordine']},
    'crea_ordine': {'type': 'object', 'properties': {'codice': {'type': 'string'}, 'quantita': {'type': 'integer'}}, 'required': ['codice', 'quantita']},
}


class ProviderSimulato(LLMProvider):
    def __init__(self, messages):
        self.messages = iter(messages)

    def chat(self, messages, tools):
        next_message = next(self.messages)
        if isinstance(next_message, Exception):
            raise next_message
        return {'message': next_message, 'prompt_tokens': 30, 'completion_tokens': 8}


class ClientLocale:
    def __init__(self, db):
        self.db = db

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name=n, description=n, input_schema=s)
                                      for n, s in SCHEMAS.items()])

    async def call_tool(self, name, args):
        funcs = {
            'cerca_prodotti': lambda: search_products(args['query'], self.db),
            'elenca_catalogo': lambda: list_catalog(args.get('categoria', ''), args.get('pagina', 1), self.db),
            'verifica_disponibilita': lambda: check_stock(args['codice'], self.db),
            'consulta_ordine': lambda: get_order(args['numero_ordine'], self.db),
            'crea_ordine': lambda: create_order(args['codice'], args['quantita'], self.db),
        }
        return SimpleNamespace(is_error=False, structured_content=funcs[name](), content=[])


class ClientConErrore:
    def __init__(self, client):
        self.client = client

    async def list_tools(self):
        return await self.client.list_tools()

    async def call_tool(self, name, args):
        raise RuntimeError('Errore simulato di comunicazione con il tool')


def tool(name, **args):
    return {'role': 'assistant', 'content': '', 'tool_calls': [
        {'function': {'name': name, 'arguments': args}}]}


def risposta(text):
    return {'role': 'assistant', 'content': text}


SCENARI = [
    ('00 elenco catalogo', 'Che prodotti ci sono in magazzino?', [tool('elenca_catalogo'), risposta('Il negozio offre 8 categorie, con 64 prodotti disponibili.')], False, 'catalogo'),
    ('00b ricerca generica', 'Che prodotti ci sono in magazzino?', [tool('cerca_prodotti', query='prodotti'), risposta('Ci sono 64 prodotti disponibili in 8 categorie.')], False, 'catalogo'),
    ('01 ricerca prodotto', 'Cerca tastiere', [tool('cerca_prodotti', query='tastiere'), risposta('Ho trovato una tastiera.')], False, None),
    ('02 disponibilita', 'Quante tastiere ci sono?', [tool('verifica_disponibilita', codice='SKU-001'), risposta('12 tastiere disponibili.')], False, None),
    ('03 ordine esistente', 'Mostrami ordine 1001', [tool('consulta_ordine', numero_ordine=1001), risposta('Ordine 1001 trovato.')], False, None),
    ('04 acquisto confermato', 'Compra 2 tastiere', [tool('crea_ordine', codice='SKU-001', quantita=2), risposta('Ordine eseguito.')], True, 'creato'),
    ('05 conferma negata', 'Compra 2 tastiere', [tool('crea_ordine', codice='SKU-001', quantita=2), risposta('Ricevuto.')], False, 'annullato'),
    ('06 scorte insufficienti', 'Compra 20 tastiere', [tool('crea_ordine', codice='SKU-001', quantita=20), risposta('Scorte insufficienti.')], True, 'scorte'),
    ('07 SKU inesistente', 'Controlla SKU-999', [tool('verifica_disponibilita', codice='SKU-999'), risposta('Prodotto non trovato.')], False, 'non_trovato'),
    ('08 parametri errati', 'Compra due tastiere', [tool('crea_ordine', codice='SKU-001', quantita='due'), risposta('Quantita non valida.')], True, 'parametri'),
    ('09 tool inesistente', 'Invoca un tool inesistente', [tool('cancella_ordine', numero_ordine=1001), risposta('Tool non disponibile.')], False, 'inesistente'),
    ('10 errore del tool', 'Controlla il magazzino', [tool('verifica_disponibilita', codice='SKU-001'), risposta('Il controllo non e disponibile.')], False, 'errore_tool'),
    ('11 richiesta ambigua', 'Vorrei acquistare qualcosa', [risposta('Quale prodotto e quante unita desideri?')], False, 'ambigua'),
    ('12 fuori ambito', 'Dimmi il meteo a Roma', [risposta('Posso aiutarti solo con catalogo e ordini.')], False, 'fuori_ambito'),
    ('13 limite iterazioni', 'Controlla piu volte', [tool('verifica_disponibilita', codice='SKU-001'), tool('verifica_disponibilita', codice='SKU-001')], False, 'limite'),
    ('14 modello non disponibile', 'Controlla un prodotto', [RuntimeError('Modello simulato non disponibile')], False, 'errore_modello'),
    ('15 errore dopo invio ordine', 'Compra due tastiere', [tool('crea_ordine', codice='SKU-001', quantita=2), tool('crea_ordine', codice='SKU-001', quantita=2), risposta('Risposta non affidabile.')], True, 'scrittura_incerta'),
]


def contiene_evento(events, event, term):
    return any(e.get('event') == event and term in json.dumps(e, ensure_ascii=False).casefold()
               for e in events)


def controlla(nome, esito, answer, events, stock, n_ordini, baseline_orders, next_order):
    if esito == 'creato':
        assert stock == 10 and n_ordini == baseline_orders + 1, 'Ordine non salvato correttamente'
        assert str(next_order) in answer and contiene_evento(events, 'human_confirmation', 'true')
    else:
        assert stock == 12 and n_ordini == baseline_orders, 'Scrittura non autorizzata o scorte alterate'
    if esito == 'catalogo':
        assert contiene_evento(events, 'tool_result', 'totale_prodotti')
        assert contiene_evento(events, 'tool_result', 'categorie')
    if esito == 'annullato':
        assert 'annullato' in answer.lower() and contiene_evento(events, 'human_confirmation', 'false')
    if esito == 'scorte':
        assert contiene_evento(events, 'tool_result', 'scorte insufficienti')
    if esito == 'non_trovato':
        assert contiene_evento(events, 'tool_result', 'non trovato')
    if esito == 'parametri':
        assert contiene_evento(events, 'tool_result', 'parametri non validi')
        assert not any(e.get('event') == 'human_confirmation' for e in events)
    if esito == 'inesistente':
        assert contiene_evento(events, 'tool_result', 'non disponibile')
    if esito == 'errore_tool':
        assert contiene_evento(events, 'tool_result', 'fallita')
    if esito == 'ambigua':
        assert '?' in answer and not any(e.get('event') == 'tool_requested' for e in events)
    if esito == 'fuori_ambito':
        assert not any(e.get('event') == 'tool_requested' for e in events)
    if esito == 'limite':
        assert 'limite di iterazioni' in answer
    if esito == 'scrittura_incerta':
        assert 'incerto' in answer and contiene_evento(events, 'tool_result', 'esito precedente incerto')
        assert sum(e.get('event') == 'human_confirmation' for e in events) == 1
    if esito == 'errore_modello':
        assert 'Errore del modello' in answer and contiene_evento(events, 'model_error', 'non disponibile')
    if nome.startswith('01'):
        assert contiene_evento(events, 'tool_result', 'sku-001')
    if nome.startswith('02'):
        assert contiene_evento(events, 'tool_result', '12')
    if nome.startswith('03'):
        assert contiene_evento(events, 'tool_result', '1001')


async def esegui_scenario(scenario, modalita, log_file):
    nome, prompt, replies, conferma, esito = scenario
    # Su Windows il processo MCP può trattenere brevemente il file SQLite aperto. della cartella temporanea.
    with tempfile.TemporaryDirectory(prefix='asteria_test_', ignore_cleanup_errors=True) as temp:
        db = Path(temp) / 'scenario.db'
        init_db(db)
        with sqlite3.connect(db) as conn:
            baseline_orders = conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
            next_order = conn.execute('SELECT MAX(id) FROM orders').fetchone()[0] + 1
        env_prev = os.environ.get('ASTERIA_DB')
        os.environ['ASTERIA_DB'] = str(db)
        logger = JsonlLogger(log_file)
        provider = ProviderSimulato(replies)
        try:
            if modalita == 'mcp':
                from mcp import Client, StdioServerParameters
                params = StdioServerParameters(command=sys.executable,
                    args=[str(BASE / 'mcp_server.py')], env=os.environ.copy())
                async with Client(params) as client:
                    obj = ClientConErrore(client) if esito in ('errore_tool', 'scrittura_incerta') else client
                    answer = await run_agent(obj, prompt, provider, logger,
                                              lambda question: conferma,
                                              max_steps=2 if esito == 'limite' else 6)
            else:
                client = ClientLocale(db)
                obj = ClientConErrore(client) if esito in ('errore_tool', 'scrittura_incerta') else client
                answer = await run_agent(obj, prompt, provider, logger,
                                          lambda question: conferma,
                                          max_steps=2 if esito == 'limite' else 6)
        finally:
            if env_prev is None:
                os.environ.pop('ASTERIA_DB', None)
            else:
                os.environ['ASTERIA_DB'] = env_prev
        with sqlite3.connect(db) as conn:
            n_ordini = conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        stock = check_stock('SKU-001', db)['quantita_disponibile']
        events = []
        for line in log_file.read_text(encoding='utf-8').splitlines():
            try:
                e = json.loads(line)
                if e.get('request_id') == logger.request_id:
                    events.append(e)
            except json.JSONDecodeError:
                pass
        try:
            controlla(nome, esito, answer, events, stock, n_ordini, baseline_orders, next_order)
            stato, dettaglio = 'OK', ''
        except AssertionError as exc:
            stato, dettaglio = 'KO', str(exc)
        return [nome, prompt, esito or 'lettura', answer, stock, n_ordini, stato, dettaglio,
                logger.request_id]


async def main():
    parser = argparse.ArgumentParser(description='Test degli scenari del PW26')
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument('--mcp', action='store_true', help='Usa il vero server MCP (senza Ollama)')
    grp.add_argument('--locale', action='store_true', help='Usa il database direttamente (senza MCP/Ollama)')
    args = parser.parse_args()
    dest = BASE / 'risultati'
    dest.mkdir(exist_ok=True)
    logfile = BASE / 'logs' / 'test_scenari.jsonl'
    logfile.parent.mkdir(exist_ok=True)
    logfile.write_text('', encoding='utf-8')
    righe = []
    modo = 'mcp' if args.mcp else 'locale'
    for scenario in SCENARI:
        try:
            row = await esegui_scenario(scenario, modo, logfile)
        except Exception as exc:
            row = [scenario[0], scenario[1], scenario[4] or 'lettura', '', '-', '-',
                   'KO', repr(exc), '']
        righe.append(row)
        print(f'{row[6]}  {row[0]}' + (f' - {row[7]}' if row[7] else ''))
    csv_path = dest / 'scenari_automatici.csv'
    with csv_path.open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file, delimiter=';')
        writer.writerow(['Scenario', 'Richiesta', 'Esito atteso', 'Risposta simulata',
                         'Scorte finali', 'Numero ordini', 'Esito', 'Dettagli', 'ID log'])
        writer.writerows(righe)
    passati = sum(r[6] == 'OK' for r in righe)
    print(f'\n{passati}/{len(righe)} scenari superati (LLM simulato, tool {modo}).')
    print(f'Report: {csv_path}\nLog: {logfile}')
    if passati != len(righe):
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
