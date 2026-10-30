import csv
import json
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOG = BASE / "logs" / "agent.jsonl"
DEST = BASE / "risultati" / "consumi_token.csv"


def main():
    if not LOG.exists():
        print("Nessun log trovato. Avvia prima main.py e fai qualche richiesta.")
        return
    richieste = defaultdict(lambda: {'richiesta': '', 'input': 0, 'output': 0,
                                      'chiamate_modello': 0, 'tool': [], 'esito': ''})
    for line in LOG.read_text(encoding='utf-8').splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = e.get('request_id') or 'senza_id'
        info = richieste[rid]
        if e.get('event') == 'user_request':
            info['richiesta'] = e.get('text', '')
        elif e.get('event') == 'model_response':
            info['chiamate_modello'] += 1
            info['input'] += e.get('prompt_tokens') or 0
            info['output'] += e.get('completion_tokens') or 0
        elif e.get('event') == 'tool_result':
            info['tool'].append(e.get('tool', ''))
        elif e.get('event') == 'agent_stop':
            info['esito'] = e.get('reason', '')
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with DEST.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['id', 'richiesta', 'chiamate_modello', 'token_input',
                         'token_output', 'token_totali', 'tool', 'arresto'])
        for rid, item in richieste.items():
            writer.writerow([rid, item['richiesta'], item['chiamate_modello'],
                             item['input'], item['output'], item['input'] + item['output'],
                             ', '.join(item['tool']), item['esito']])
    print(f'Analizzate {len(richieste)} richieste. CSV: {DEST}')
    print('Token complessivi:', sum(t['input'] + t['output'] for t in richieste.values()))
    print('Questi sono i token registrati durante le esecuzioni, non una stima economica.')


if __name__ == '__main__':
    main()
