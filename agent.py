"""Ciclo agentico e integrazione con il modello Ollama."""

from __future__ import annotations

import asyncio
import json
import re
import urllib.error
import urllib.request
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

LOG_PATH = Path(__file__).resolve().parent / "logs" / "agent.jsonl"
READ_TOOLS = {"cerca_prodotti", "elenca_catalogo", "verifica_disponibilita", "consulta_ordine"}
WRITE_TOOLS = {"crea_ordine"}
MAX_STEPS = 6

SYSTEM_PROMPT = (
    "Sei l'assistente di un negozio di tecnologia fittizio Asteria Store. "
    "Rispondi in italiano usando esclusivamente i dati ottenuti dai tool per disponibilita', "
    "prezzi e ordini. Per domande generali (quali prodotti avete, cosa c'e' in "
    "magazzino, elenco categorie) usa elenca_catalogo; per un articolo specifico "
    "usa cerca_prodotti e poi verifica_disponibilita se serve. "
    "elenca_catalogo restituisce una pagina di 12 prodotti: non presentarla come l'intero "
    "catalogo, indica le categorie e la possibilità di chiedere la pagina successiva. "
    "Non inventare dati. Se una richiesta e' ambigua, chiedi chiarimenti. "
    "Quando l'utente esprime chiaramente la volonta' di acquistare o creare un ordine, "
    "chiama il tool crea_ordine con codice SKU e quantita' esatti, dopo gli eventuali "
    "tool di lettura necessari. Non chiedere mai una conferma a parole nella tua risposta: "
    "la richiesta di conferma SI/NO e' gestita dal programma quando invoca crea_ordine. "
    "Una semplice risposta 'si' dell'utente non e' di per se' un'autorizzazione alla scrittura: "
    "il software chiedera' sempre una conferma separata. "
    "Non utilizzare tool non presenti nell'elenco disponibile. "
    "Se la ricerca non trova corrispondenze, non dedurre che le scorte siano zero: "
    "chiedi una parola chiave diversa. "
    "Nella risposta finale non esporre ragionamenti, analisi interne o tag <think>. "
    "Rispondi in modo breve e chiaro."
)


class ProviderError(RuntimeError):
    """Problema nella comunicazione con il modello."""


class LLMProvider(ABC):
    """Interfaccia sostituibile: qui si potrebbe aggiungere un altro provider."""

    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Restituisce {message, prompt_tokens, completion_tokens}."""


class OllamaProvider(LLMProvider):
    def __init__(self, model: str = "qwen3:4b", base_url: str = "http://127.0.0.1:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_ctx": 4096},
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/chat", data=body,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(
                f"Ollama ha restituito HTTP {exc.code}: {detail}. "
                f"Controlla il modello con 'ollama list' e, se manca, 'ollama pull {self.model}'."
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(
                "Ollama non risponde su 127.0.0.1:11434. "
                "Apri Ollama e verifica con 'ollama list'."
            ) from exc
        except (ValueError, KeyError) as exc:
            raise ProviderError(f"Risposta non valida da Ollama: {exc}") from exc

        return {
            "message": result.get("message") or {},
            "prompt_tokens": result.get("prompt_eval_count"),
            "completion_tokens": result.get("eval_count"),
        }


class JsonlLogger:
    def __init__(self, path: Path = LOG_PATH):
        self.path = path
        self.request_id = None
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **fields: Any) -> None:
        record = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "request_id": self.request_id, "event": event, **fields}
        with self.path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def validate_arguments(schema: dict, args: Any) -> str | None:
    """Controlla i parametri prima di inoltrarli al server MCP."""
    if not isinstance(args, dict):
        return "I parametri del tool devono essere un oggetto JSON."
    props = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in args:
            return f"Parametro obbligatorio mancante: {name}."
    for name, value in args.items():
        if name not in props:
            return f"Parametro non riconosciuto: {name}."
        kind = props[name].get("type")
        if kind == "string" and not isinstance(value, str):
            return f"Parametro {name}: serve una stringa."
        if kind == "integer" and type(value) is not int:
            return f"Parametro {name}: serve un numero intero."
        if kind == "number" and (type(value) not in (float, int)):
            return f"Parametro {name}: serve un numero."
        if kind == "boolean" and type(value) is not bool:
            return f"Parametro {name}: serve un booleano."
    return None


def clean_model_answer(raw: Any) -> str:
    """Rimuove eventuali blocchi <think> lasciati dal modello nel testo finale.

    In alcune risposte Qwen3 puo' inserire il testo di riflessione nel campo
    content, talvolta perfino senza il tag di apertura <think>. La parte visibile
    all'utente deve rimanere soltanto quella successiva a </think>.
    """
    text = str(raw or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.I | re.S)
    if re.search(r"</think>", text, flags=re.I):
        text = re.split(r"</think>", text, flags=re.I)[-1]
    if re.search(r"<think>", text, flags=re.I):
        text = re.split(r"<think>", text, flags=re.I)[0]
    return text.strip()



def is_explicit_purchase_request(text: str, history: list[dict] | None = None) -> bool:
    """Rileva una richiesta esplicita di acquisto senza eseguire scritture."""
    lower = text.strip().casefold()
    if re.search(r"\b(acquist(?:are|o|iamo)|compr(?:are|o|iamo)|ordin(?:are|o|iamo)|"
                 r"compra|acquista|crea(?:re)?\s+(?:un\s+)?ordine)\b", lower):
        return True
    if lower in {"si", "sì", "certo", "confermo", "ok", "procedi"} and history:
        # Un assenso si collega soltanto al turno precedente, non a messaggi
        # arbitrariamente vecchi. La conferma di sicurezza restera' separata.
        last_assistant = history[-1] if history else {}
        prev_user = history[-2] if len(history) >= 2 else {}
        if last_assistant.get("role") == "assistant" and prev_user.get("role") == "user":
            question = last_assistant.get("content", "").casefold()
            return bool(re.search(r"(?:vuoi|desideri|procedere|procediamo|confermi|conferma).{0,90}(?:ordine|acquisto|procedere|unità|unita)|(?:ordine|acquisto).{0,90}(?:procedere|conferm)", question)) and is_explicit_purchase_request(prev_user.get("content", ""))
    return False


def asks_to_proceed(text: str) -> bool:
    """Intercetta una conferma conversazionale, NON quella dell'harness."""
    lower = clean_model_answer(text).casefold()
    return bool(re.search(r"(?:vuoi|desideri|posso|devo|confermi|procediamo|procedere|conferma).{0,100}(?:procedere|ordine|acquisto|conferma|unità|unita)|(?:ordine|acquisto).{0,100}(?:procedere|conferm)", lower)) and ("?" in lower)


def remember_turn(history: list[dict] | None, request: str, answer: str) -> None:
    """Memoria breve e controllata, senza salvare tool call non accoppiate."""
    if history is not None:
        history.extend([{"role": "user", "content": request},
                        {"role": "assistant", "content": answer}])
        # Massimo 6 scambi completi per contenere l'uso di token.
        del history[:-12]


def riepilogo_ordine(ordine: dict) -> str:
    text = f"Ordine {ordine.get('numero_ordine', '?')} creato."
    if isinstance(ordine.get("totale_eur"), (int, float)):
        text += f" Totale: {ordine['totale_eur']:.2f} EUR."
    return text


def format_result(result: Any) -> dict | list | str:
    if getattr(result, "is_error", False):
        texts = [getattr(part, "text", "") for part in result.content]
        return {"errore": "Il tool MCP ha fallito", "dettagli": texts}
    if getattr(result, "structured_content", None) is not None:
        return result.structured_content
    texts = [getattr(part, "text", "") for part in result.content]
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except (json.JSONDecodeError, TypeError):
            return texts[0]
    return texts


async def run_agent(
    client: Any,
    user_request: str,
    provider: LLMProvider,
    logger: JsonlLogger,
    confirm: Callable[[str], bool],
    max_steps: int = MAX_STEPS,
    history: list[dict] | None = None,
) -> str:
    """Ciclo: LLM -> (tool MCP -> feedback)* -> risposta / arresto."""
    if not user_request.strip():
        return "Scrivi una richiesta non vuota."
    logger.request_id = uuid.uuid4().hex[:12]
    listed = await client.list_tools()
    tool_index = {tool.name: tool for tool in listed.tools}
    available_tools = [
        {"type": "function", "function": {
            "name": tool.name, "description": tool.description or "",
            "parameters": tool.input_schema,
        }}
        for tool in listed.tools
    ]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *(history or []),
        {"role": "user", "content": user_request},
    ]
    logger.write("user_request", text=user_request, provider=type(provider).__name__)
    writes_denied = False
    writes_executed = False
    write_uncertain = False
    created_order = None
    retried_natural_confirmation = False
    for step in range(1, max_steps + 1):
        logger.write("model_request", step=step, messages=messages,
                     available_tools=sorted(tool_index))
        try:
            response = await asyncio.to_thread(provider.chat, messages, available_tools)
        except Exception as exc:
            logger.write("model_error", step=step, error=str(exc))
            if created_order is not None:
                return riepilogo_ordine(created_order)
            if write_uncertain:
                return "Esito ordine incerto: controlla i dati prima di riprovare."
            return f"Errore del modello: {exc}"
        message = response.get("message", {})
        if not isinstance(message, dict):
            logger.write("model_error", step=step, error="Messaggio non valido")
            if created_order is not None:
                return riepilogo_ordine(created_order)
            return "Il modello ha restituito una risposta non valida."
        requested = message.get("tool_calls") or []
        logger.write("model_response", step=step, content=message.get("content", ""),
                     tool_calls=requested, prompt_tokens=response.get("prompt_tokens"),
                     completion_tokens=response.get("completion_tokens"))

        if not requested:
            answer = clean_model_answer(message.get("content"))
            if not answer:
                logger.write("agent_stop", reason="empty_final_answer", step=step)
                if created_order is not None:
                    return riepilogo_ordine(created_order)
                if write_uncertain:
                    return "Esito ordine incerto: controlla i dati prima di riprovare."
                return "Il modello non ha prodotto una risposta finale leggibile. Riprova."
            # Se il modello chiede conferma a parole, ritentiamo il tool una volta.
            if (not retried_natural_confirmation and not writes_denied
                    and not writes_executed and not write_uncertain and is_explicit_purchase_request(user_request, history)
                    and asks_to_proceed(answer)):
                retried_natural_confirmation = True
                logger.write("model_retry", step=step, reason="natural_language_confirmation_instead_of_tool")
                messages.append({"role": "assistant", "content": answer})
                messages.append({"role": "system", "content": (
                    "La conferma in linguaggio naturale NON esegue l'ordine. "
                    "L'utente ha gia' richiesto esplicitamente l'acquisto. "
                    "Chiama ora crea_ordine con i parametri corretti, usando prima "
                    "i tool di lettura se mancano SKU o quantita'. La richiesta "
                    "di conferma SI/NO e' responsabilita' del programma. "
                    "Se non conosci SKU o quantita', chiedi solo il dato mancante."
                )})
                continue
            # L'LLM non puo' dichiarare riuscita una scrittura inesistente.
            if not writes_executed and re.search(
                    r"\b(?:ordine(?:\s+\d+)?\s+(?:creato|registrato|effettuato|completato)"
                    r"|acquisto\s+(?:effettuato|completato))\b",
                    answer.casefold()):
                answer = "Nessun ordine e' stato creato: il tool crea_ordine non e' stato eseguito. Riformula la richiesta."
                logger.write("model_unverified_write_claim", step=step)
            if writes_denied:
                answer = "Ordine annullato: conferma negata. Nessuna scrittura eseguita."
            elif write_uncertain:
                answer = ("Esito ordine incerto per un errore di comunicazione. "
                          "Controlla ordini e magazzino prima di riprovare.")
            elif created_order is not None:
                answer = riepilogo_ordine(created_order)
            logger.write("agent_stop", reason="final_answer", step=step)
            remember_turn(history, user_request, answer)
            return answer
        if not isinstance(requested, list):
            logger.write("agent_stop", reason="invalid_tool_calls", step=step)
            return "Il modello ha prodotto un formato tool_calls non valido."

        messages.append({"role": "assistant", "content": message.get("content") or "",
                         "tool_calls": requested})
        for call in requested:
            function = call.get("function") if isinstance(call, dict) else {}
            if not isinstance(function, dict):
                function = {}
            name = function.get("name", "")
            args = function.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = None

            logger.write("tool_requested", step=step, tool=name, arguments=args)
            if name not in tool_index:
                output = {"errore": f"Tool non disponibile: {name}."}
            else:
                invalid = validate_arguments(tool_index[name].input_schema, args)
                if invalid:
                    output = {"errore": f"Parametri non validi: {invalid}"}
                elif name in WRITE_TOOLS:
                    if writes_executed:
                        output = {"errore": "Scrittura gia' eseguita in questa richiesta. Nessun duplicato creato."}
                    elif writes_denied:
                        output = {"errore": "Operazioni di scrittura gia' rifiutate in questa richiesta."}
                    elif write_uncertain:
                        output = {"errore": "Esito precedente incerto. Non ripeto la scrittura."}
                    else:
                        question = f"ATTENZIONE: eseguire {name} con parametri {json.dumps(args, ensure_ascii=False)}?"
                        accepted = confirm(question)
                        logger.write("human_confirmation", step=step, tool=name, accepted=accepted)
                        if not accepted:
                            writes_denied = True
                            output = {"errore": "Utente ha negato la conferma. Nessuna scrittura eseguita."}
                        else:
                            try:
                                output = format_result(await client.call_tool(name, args))
                                if isinstance(output, dict) and output.get("esito") == "ordine_creato":
                                    writes_executed = True
                                    created_order = output
                            except Exception as exc:
                                write_uncertain = True
                                output = {"errore": f"Chiamata MCP fallita: {exc}",
                                          "avviso": "Esito incerto, non ripetere automaticamente."}
                elif name in READ_TOOLS:
                    try:
                        output = format_result(await client.call_tool(name, args))
                    except Exception as exc:
                        output = {"errore": f"Chiamata MCP fallita: {exc}"}
                else:
                    output = {"errore": "Tool non autorizzato: classificare come lettura o scrittura."}

            logger.write("tool_result", step=step, tool=name, result=output)
            messages.append({"role": "tool", "tool_name": name,
                             "content": json.dumps(output, ensure_ascii=False, default=str)})

    logger.write("agent_stop", reason="max_steps", limit=max_steps)
    answer = (riepilogo_ordine(created_order) if created_order else
              "Esito ordine incerto: controlla i dati prima di riprovare." if write_uncertain else
              "Ho raggiunto il limite di iterazioni senza una risposta affidabile. "
              "Prova a semplificare la richiesta.")
    remember_turn(history, user_request, answer)
    return answer
