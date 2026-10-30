import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent import JsonlLogger, LLMProvider, run_agent, validate_arguments, clean_model_answer


SCHEMAS = {
    "verifica_disponibilita": {"type": "object", "properties": {"codice": {"type": "string"}}, "required": ["codice"]},
    "crea_ordine": {"type": "object", "properties": {"codice": {"type": "string"}, "quantita": {"type": "integer"}}, "required": ["codice", "quantita"]},
}


class FakeClient:
    def __init__(self):
        self.calls = []

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name=name, description=name, input_schema=schema)
                                      for name, schema in SCHEMAS.items()])

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return SimpleNamespace(is_error=False, structured_content={"esito": "ok"}, content=[])


class FakeProvider(LLMProvider):
    def __init__(self, responses):
        self.responses = iter(responses)

    def chat(self, messages, tools):
        return {"message": next(self.responses), "prompt_tokens": 20, "completion_tokens": 6}


def request_tool(name, args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def final_answer():
    return {"role": "assistant", "content": "Operazione conclusa."}


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.logger = JsonlLogger(Path(self.temp.name) / "test.jsonl")

    def tearDown(self):
        self.temp.cleanup()

    def test_remove_qwen_thinking_prefix(self):
        noisy = "Okay, I will reason in English...\n</think>\nDisponibili 12 tastiere."
        self.assertEqual(clean_model_answer(noisy), "Disponibili 12 tastiere.")
        normal = "<think>Ragionamento interno</think>Ci sono 12 tastiere."
        self.assertEqual(clean_model_answer(normal), "Ci sono 12 tastiere.")

    def test_validation(self):
        schema = SCHEMAS["crea_ordine"]
        self.assertIsNone(validate_arguments(schema, {"codice": "SKU-001", "quantita": 2}))
        self.assertIsNotNone(validate_arguments(schema, {"codice": "SKU-001", "quantita": "due"}))
        self.assertIsNotNone(validate_arguments(schema, {"codice": "SKU-001"}))

    def test_read_tool_is_called(self):
        client = FakeClient()
        provider = FakeProvider([
            request_tool("verifica_disponibilita", {"codice": "SKU-001"}), final_answer()
        ])
        response = asyncio.run(run_agent(client, "Quante tastiere?", provider, self.logger,
                                         confirm=lambda _: False))
        self.assertEqual(response, "Operazione conclusa.")
        self.assertEqual(len(client.calls), 1)

    def test_write_is_denied_without_side_effects(self):
        client = FakeClient()
        provider = FakeProvider([
            request_tool("crea_ordine", {"codice": "SKU-001", "quantita": 2}), final_answer()
        ])
        asyncio.run(run_agent(client, "Compra 2 tastiere", provider, self.logger,
                              confirm=lambda _: False))
        self.assertEqual(client.calls, [])

    def test_invalid_arguments_do_not_call_tool(self):
        client = FakeClient()
        provider = FakeProvider([
            request_tool("crea_ordine", {"codice": "SKU-001", "quantita": "due"}), final_answer()
        ])
        asyncio.run(run_agent(client, "Compra due tastiere", provider, self.logger,
                              confirm=lambda _: True))
        self.assertEqual(client.calls, [])

    def test_unknown_tool_is_rejected(self):
        client = FakeClient()
        provider = FakeProvider([request_tool("tool_inventato", {}), final_answer()])
        asyncio.run(run_agent(client, "Prova tool inesistente", provider, self.logger,
                              confirm=lambda _: True))
        self.assertEqual(client.calls, [])

    def test_max_steps_stops_agent(self):
        client = FakeClient()
        provider = FakeProvider([request_tool("verifica_disponibilita", {"codice": "SKU-001"})])
        answer = asyncio.run(run_agent(client, "Prova limite", provider, self.logger,
                                       confirm=lambda _: True, max_steps=1))
        self.assertIn("limite di iterazioni", answer)


if __name__ == "__main__":
    unittest.main()

class ConversationalOrderTests(unittest.TestCase):
    """Regressioni dalla prova reale: proposta ordine seguita da 'si'."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.logger = JsonlLogger(Path(self.temp.name) / "session.jsonl")

    def tearDown(self):
        self.temp.cleanup()

    def test_purchase_question_is_retried_with_tool_and_confirmation(self):
        client = FakeClient()
        provider = FakeProvider([
            request_tool("verifica_disponibilita", {"codice": "SKU-001"}),
            {"role": "assistant", "content": "Hai trovato 12 tastiere. Vuoi procedere con l'ordine?"},
            request_tool("crea_ordine", {"codice": "SKU-001", "quantita": 2}),
            final_answer(),
        ])
        prompts = []
        history = []
        result = asyncio.run(run_agent(
            client, "Vorrei acquistare 2 tastiere meccaniche", provider, self.logger,
            confirm=lambda question: prompts.append(question) or False,
            history=history,
        ))
        self.assertIn("annullato", result)
        self.assertEqual(client.calls, [("verifica_disponibilita", {"codice": "SKU-001"})])
        self.assertEqual(len(prompts), 1)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[1]["role"], "assistant")

    def test_history_is_included_in_next_model_turn(self):
        class CapturingProvider(FakeProvider):
            def __init__(self):
                super().__init__([final_answer()])
                self.messages = []

            def chat(self, messages, tools):
                self.messages = [m.copy() for m in messages]
                return super().chat(messages, tools)

        client = FakeClient()
        provider = CapturingProvider()
        history = [
            {"role": "user", "content": "Cerco una tastiera meccanica"},
            {"role": "assistant", "content": "Sono disponibili 12 tastiere."},
        ]
        asyncio.run(run_agent(client, "Quanto costano?", provider, self.logger,
                              confirm=lambda _: False, history=history))
        self.assertEqual(provider.messages[1], {"role": "user", "content": "Cerco una tastiera meccanica"})
        self.assertEqual(provider.messages[2]["role"], "assistant")
        self.assertEqual(provider.messages[3], {"role": "user", "content": "Quanto costano?"})
        self.assertEqual(len(history), 4)

    def test_yes_without_previous_order_is_not_interpreted_as_purchase(self):
        from agent import is_explicit_purchase_request
        self.assertFalse(is_explicit_purchase_request("si", []))
        self.assertTrue(is_explicit_purchase_request("si", [
            {"role": "user", "content": "Vorrei acquistare 2 tastiere"},
            {"role": "assistant", "content": "Vuoi procedere con l'ordine?"},
        ]))

    def test_duplicate_tool_write_is_rejected(self):
        class SuccessClient(FakeClient):
            async def call_tool(self, name, args):
                self.calls.append((name, args))
                return SimpleNamespace(is_error=False, structured_content={"esito": "ordine_creato", "numero_ordine": 1181}, content=[])

        client = SuccessClient()
        provider = FakeProvider([
            request_tool("crea_ordine", {"codice": "SKU-001", "quantita": 2}),
            request_tool("crea_ordine", {"codice": "SKU-001", "quantita": 2}),
            final_answer(),
        ])
        prompts = []
        asyncio.run(run_agent(client, "Acquista 2 tastiere", provider, self.logger,
                              confirm=lambda question: prompts.append(question) or True))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(prompts), 1)
