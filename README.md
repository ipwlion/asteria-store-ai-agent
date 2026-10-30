# Asteria Store AI Agent

Questo repository contiene il project work 26 del corso di Informatica per le
Aziende Digitali (L-31). L'obiettivo è provare a integrare un assistente
basato su un modello linguistico in un piccolo sistema informativo, usando un
server MCP per separare la parte conversazionale dalle operazioni sul database.

Asteria Store è un negozio online inventato di prodotti tecnologici. Il
programma permette di cercare articoli, controllare le scorte, leggere gli
ordini presenti e inserire un nuovo ordine. L'esecuzione è locale: non è
previsto un server pubblico e non vengono usati dati personali reali.

Le tecnologie principali sono Python, SQLite, MCP, Ollama e Qwen3 4B. Il ciclo
agentico è scritto in `agent.py` per rendere visibili i passaggi principali,
senza usare framework come LangChain o LangGraph.

## 1. Installazione su Windows

Occorrono Python e Ollama già installati. Apri PowerShell nella cartella `Asteria_Store_AI_Agent`:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull qwen3:4b
```

Avvia Ollama normalmente e verifica che risponda tramite `ollama list`.

## 2. Avvio

```powershell
.\.venv\Scripts\python.exe setup_database.py
.\.venv\Scripts\python.exe test_mcp.py
.\.venv\Scripts\python.exe main.py
```

In alternativa, dopo l'installazione, fai doppio clic su `avvia.bat`.

Richieste di esempio:

- `Cerca una tastiera meccanica`
- `Quante tastiere meccaniche SKU-001 ci sono?`
- `Mostrami l'ordine 1001`
- `Vorrei acquistare 2 tastiere meccaniche SKU-001`
- `Vorrei acquistare 999 tastiere meccaniche SKU-001`
- `Cerca monitor 27 pollici`
- `Che prodotti ci sono in magazzino?`
- `Mostrami la categoria Tastiere`
- `Mostrami la seconda pagina del catalogo`

Per terminare scrivi `esci`. Prima di **ogni scrittura**, il programma chiede `Confermi? Scrivi SI per procedere:`. Ogni altro testo nega la modifica. L'ordine viene scritto su SQLite solo dopo la conferma, e la disponibilità viene verificata anche dal database.

Le domande generali sul catalogo usano il tool di lettura `elenca_catalogo`, con 12 prodotti per pagina e riepilogo delle categorie. Per cercare un articolo specifico resta disponibile `cerca_prodotti`. Una richiesta generica come `Vorrei una tastiera` può richiedere di precisare il modello.

## 3. Dati inventati

Alla prima esecuzione `setup_database.py` crea:

| Tabella | Contenuto iniziale |
|---|---:|
| `products` | 64 prodotti di 8 categorie |
| `customers` | 121 codici cliente fittizi, senza nomi o contatti |
| `orders` | 180 ordini storici simulati |
| `order_items` | 369 righe d'ordine |

I dati sono generati con parametri fissi in `database.py`, quindi sono riproducibili. Gli ordini storici **non** modificano la giacenza iniziale: questa rappresenta la disponibilità attuale del magazzino. Il primo nuovo ordine parte da `1181`. Le richieste effettuate con l'agente creano ordini aggiuntivi e aggiornano le scorte.

Per esportare le quattro tabelle in CSV:

```powershell
.\.venv\Scripts\python.exe export_data.py
```

I CSV saranno salvati in `data/export/`.

Per ricreare il DB iniziale, chiudi prima l'assistente e usa:

```powershell
.\.venv\Scripts\python.exe reset_database.py
```

Il comando richiede di scrivere `RIPRISTINA` e conserva automaticamente una copia di backup del database precedente.

**Attenzione:** è un progetto nuovo con uno schema dati diverso dal vecchio prototipo SmartBusiness. Estrarlo in una nuova cartella. **Non copiare** il vecchio file `azienda.db` dentro questo progetto. Puoi mantenere il precedente come archivio.

## 4. Test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe run_scenarios.py --locale
.\.venv\Scripts\python.exe run_scenarios.py --mcp
```

- `unittest`: logica Python, controlli e database (inclusa la consultazione del catalogo).
- `--locale`: 17 scenari con modello simulato e funzioni Python.
- `--mcp`: gli stessi scenari con **server MCP reale**, ma modello simulato. I test non modificano il DB principale, usano database temporanei.

Su Windows la chiusura del processo MCP potrebbe lasciare per alcuni istanti il file temporaneo occupato. Lo script usa `ignore_cleanup_errors=True` per evitare che un errore di pulizia del file faccia fallire lo scenario già verificato. Non influenza l'esito del test sui dati.

I test simulati **non sostituiscono i test con il modello Qwen3 reale** previsti dalla traccia. I test reali vanno eseguiti e documentati con log e screenshot quando l'integrazione sarà confermata sul PC.

### Verifica locale del repository

La verifica eseguita il 30/10/2026 ha prodotto questi risultati:

- `python -m unittest discover -s tests -v`: **27/27 test superati**.
- `python run_scenarios.py --locale`: **17/17 scenari superati**.
- `python run_scenarios.py --mcp`: **17/17 scenari superati** usando il server MCP stdio reale e un provider LLM simulato.
- `python test_mcp.py`: elenco dei cinque tool e chiamata a `verifica_disponibilita` superati.
- `python token_report.py`: report rigenerato da 6 richieste presenti nel log, per **30.559 token registrati**.

Questi risultati verificano il trasporto MCP e l'harness, ma non attestano l'esecuzione di Qwen3. Le prove con il modello effettivo devono essere raccolte separatamente con prompt, risposta, `request_id`, log e screenshot; almeno una prova deve documentare una conferma negata e una una scrittura confermata con confronto delle scorte prima/dopo. I file generati in `logs/` e `risultati/` sono esclusi da Git per evitare di pubblicare dati di esecuzione locali.

Durante una prova reale controllata con `qwen3:4b` sono state eseguite 10 richieste isolate su un database temporaneo. Nove casi hanno prodotto il comportamento atteso; un caso ha rilevato una falsa dichiarazione di ordine creato senza chiamata al tool e senza modifica del database. Il log `logs/qwen3_reali.jsonl` conserva questa anomalia come evidenza di human-in-the-loop e di gestione dell'errore, non come successo del modello. Il controllo dell'harness è stato rafforzato per rifiutare anche dichiarazioni con numero d'ordine, ad esempio `Ordine 1182 creato`, quando il tool non è stato eseguito.

## 5. Log e token

L'agente salva gli eventi nel file `logs/agent.jsonl`, con ID della richiesta, passi del modello, tool invocati, parametri, risultato, conferme e token restituiti da Ollama.

Per creare il report CSV dei consumi effettivi:

```powershell
.\.venv\Scripts\python.exe token_report.py
```

Il file risultante è `risultati/consumi_token.csv`. Il modello locale non genera un costo a consumo API; la stima economica nella relazione si baserà su ipotesi dichiarate (hardware, energia e tempo dell'operatore).

## 6. File principali

| File | Funzione |
|---|---|
| `main.py` | Avvio e interfaccia testuale |
| `agent.py` | Harness, gestione chiamate, conferme, arresto, log e provider LLM |
| `mcp_server.py` | Server MCP con cinque tool (quattro letture, una scrittura) |
| `database.py` | SQLite, catalogo sintetico, ordini e magazzino |
| `setup_database.py` | Crea e descrive il DB iniziale |
| `test_mcp.py` | Verifica del server MCP senza Ollama |
| `run_scenarios.py` | 17 scenari automatici |
| `token_report.py` | Report dei token letti dai log |
| `reset_database.py` | Ripristino dei dati con backup |
| `export_data.py` | Esporta il DB in CSV |
| `tests/` | Test unitari |

## 7. Limiti e sviluppi possibili

È una demo didattica, non un sistema di vendita utilizzabile con clienti veri.
Non gestisce pagamenti, autenticazione, indirizzi di spedizione o informazioni
personali. Il modello può sbagliare la selezione del tool; per questo i
parametri e la disponibilità vengono controllati anche dal back-end. Prima di
una scrittura è inoltre richiesta una conferma esplicita dell'utente.

Come sviluppi successivi si potrebbero aggiungere un'interfaccia web, una
gestione dei clienti più realistica e prove con più modelli. In questa versione
ho preferito mantenere il progetto piccolo, così da poter verificare con
chiarezza il flusso tra agente, MCP e database.

Nella relazione universitaria andranno indicati anche gli strumenti AI utilizzati per lo sviluppo, come richiesto dalla traccia, e dovranno essere raccolte prove di esecuzione effettiva.
