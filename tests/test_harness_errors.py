import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent import JsonlLogger, run_agent
from test_agent import FakeClient, FakeProvider, request_tool


class TestCasiAggiuntivi(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.log = JsonlLogger(Path(self.temp.name) / 'test.jsonl')

    def tearDown(self):
        self.temp.cleanup()

    def test_errore_comunicazione_non_ripete_ordine(self):
        class ErroreScrittura(FakeClient):
            async def call_tool(self, name, args):
                self.calls.append((name, args))
                raise RuntimeError('Connessione persa')

        client = ErroreScrittura()
        provider = FakeProvider([
            request_tool('crea_ordine', {'codice': 'SKU-001', 'quantita': 2}),
            request_tool('crea_ordine', {'codice': 'SKU-001', 'quantita': 2}),
            {'role': 'assistant', 'content': 'Ordine creato.'},
        ])
        confirmations = []
        answer = asyncio.run(run_agent(client, 'Acquista 2 tastiere', provider,
            self.log, lambda q: confirmations.append(q) or True))
        self.assertIn('incerto', answer)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(confirmations), 1)

    def test_risposta_corretta_se_llm_cade_dopo_ordine(self):
        class OrdineCreato(FakeClient):
            async def call_tool(self, name, args):
                self.calls.append((name, args))
                return SimpleNamespace(is_error=False, content=[], structured_content={
                    'esito': 'ordine_creato', 'numero_ordine': 1181, 'totale_eur': 159.8})

        client = OrdineCreato()
        provider = FakeProvider([
            request_tool('crea_ordine', {'codice': 'SKU-001', 'quantita': 2}),
        ])
        answer = asyncio.run(run_agent(client, 'Acquista 2 tastiere', provider,
            self.log, lambda _: True))
        self.assertIn('1181', answer)
        self.assertIn('159.80', answer)
        self.assertEqual(len(client.calls), 1)

    def test_log_contiene_token_e_id(self):
        client = FakeClient()
        provider = FakeProvider([{'role': 'assistant', 'content': 'Ciao!'}])
        asyncio.run(run_agent(client, 'Ciao', provider, self.log, lambda _: False))
        records = [json.loads(x) for x in self.log.path.read_text().splitlines()]
        ids = {r['request_id'] for r in records}
        self.assertEqual(len(ids), 1)
        self.assertTrue(all(ids))
        metrics = next(e for e in records if e['event'] == 'model_response')
        self.assertEqual(metrics['prompt_tokens'], 20)
        self.assertEqual(metrics['completion_tokens'], 6)


if __name__ == '__main__':
    unittest.main()
