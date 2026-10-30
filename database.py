"""Database SQLite e dati sintetici del negozio Asteria Store."""

from __future__ import annotations

import os
import random
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = Path(os.environ.get("ASTERIA_DB", str(BASE_DIR / "data" / "asteria_store.db")))

# Tutti i prodotti sono inventati. Non vengono utilizzati dati personali.
CATALOGO = {
    "Tastiere": [
        ("Tastiera meccanica", 7990, 12), ("Tastiera compatta wireless", 6490, 19),
        ("Tastiera ergonomica", 8990, 11), ("Tastiera slim USB", 2490, 42),
        ("Tastiera gaming RGB", 9990, 16), ("Tastiera Bluetooth multi-dispositivo", 7490, 8),
        ("Tastiera numerica esterna", 1990, 30), ("Tastiera silenziosa da ufficio", 3990, 25),
    ],
    "Mouse": [
        ("Mouse wireless", 2990, 25), ("Mouse ergonomico verticale", 4490, 15),
        ("Mouse gaming", 5990, 20), ("Mouse USB ottico", 1490, 50),
        ("Mouse Bluetooth", 3490, 33), ("Mouse compatto da viaggio", 2290, 27),
        ("Trackball wireless", 6990, 6), ("Mouse silenzioso", 2790, 31),
    ],
    "Monitor": [
        ("Monitor 24 pollici", 15900, 7), ("Monitor 27 pollici IPS", 22900, 11),
        ("Monitor 32 pollici 4K", 39900, 5), ("Monitor portatile USB-C", 18900, 9),
        ("Monitor ultrawide 34 pollici", 49900, 3), ("Monitor gaming 165Hz", 27900, 13),
        ("Monitor professionale QHD", 34900, 6), ("Monitor 22 pollici", 12900, 17),
    ],
    "Audio": [
        ("Cuffie USB", 4950, 15), ("Cuffie Bluetooth", 8990, 12),
        ("Auricolari wireless", 5490, 22), ("Microfono da tavolo USB", 6990, 14),
        ("Casse stereo compatte", 3990, 18), ("Headset call center", 5990, 10),
        ("Soundbar per monitor", 7990, 8), ("Microfono lavalier", 2990, 26),
    ],
    "Video": [
        ("Webcam HD", 3990, 9), ("Webcam Full HD", 6990, 16),
        ("Webcam 4K", 14900, 6), ("Luce LED per videochiamate", 2990, 35),
        ("Supporto webcam", 1590, 29), ("Videocamera per sale riunioni", 27900, 4),
        ("Treppiede da scrivania", 1990, 32), ("Scheda acquisizione HDMI", 7990, 10),
    ],
    "Accessori": [
        ("Hub USB-C", 2490, 18), ("Docking station USB-C", 13900, 9),
        ("Adattatore HDMI USB-C", 1890, 39), ("Cavo USB-C 2 metri", 1290, 60),
        ("Supporto notebook", 3490, 27), ("Tappetino mouse XL", 1990, 38),
        ("Borsa notebook 15 pollici", 3990, 20), ("Alimentatore USB-C 65W", 4990, 21),
    ],
    "Archiviazione": [
        ("SSD esterno 1TB", 9990, 16), ("SSD interno 500GB", 5990, 18),
        ("SSD interno 2TB", 15900, 9), ("Chiavetta USB 64GB", 1490, 45),
        ("Chiavetta USB 128GB", 2290, 41), ("Scheda microSD 256GB", 3490, 23),
        ("Hard disk esterno 2TB", 8990, 13), ("Box esterno SSD", 2490, 32),
    ],
    "Rete": [
        ("Router Wi-Fi 6", 11900, 12), ("Router Wi-Fi mesh", 18900, 8),
        ("Switch Ethernet 8 porte", 4990, 17), ("Switch Ethernet 16 porte", 11900, 11),
        ("Adattatore Wi-Fi USB", 1990, 34), ("Cavo Ethernet 5 metri", 1090, 49),
        ("Access point Wi-Fi", 9900, 14), ("Adattatore Ethernet USB-C", 2290, 28),
    ],
}

# Conserviamo alcuni codici storici della prima demo per rendere familiari le prove.
PRIMI_CODICI = {
    "Tastiera meccanica": "SKU-001", "Mouse wireless": "SKU-002",
    "Monitor 24 pollici": "SKU-003", "Cuffie USB": "SKU-004",
    "Webcam HD": "SKU-005", "Hub USB-C": "SKU-006",
}


def prodotti_demo():
    prodotti = []
    sku_n = 7
    for categoria, articoli in CATALOGO.items():
        for nome, prezzo, disponibilita in articoli:
            codice = PRIMI_CODICI.get(nome)
            if codice is None:
                codice = f"SKU-{sku_n:03d}"
                sku_n += 1
            soglia = 5 if prezzo >= 10000 else 8
            prodotti.append((codice, nome, categoria, prezzo, disponibilita, soglia))
    return prodotti


@contextmanager
def connect(db_path: str | Path | None = None):
    path = Path(db_path) if db_path is not None else Path(os.environ.get("ASTERIA_DB", str(DEFAULT_DB)))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db(db_path: str | Path | None = None):
    with connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                sku TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK(price_cents>=0),
                stock INTEGER NOT NULL CHECK(stock>=0),
                min_stock INTEGER NOT NULL CHECK(min_stock>=0)
            );
            CREATE TABLE IF NOT EXISTS customers (
                code TEXT PRIMARY KEY,
                area TEXT NOT NULL,
                customer_type TEXT NOT NULL,
                registered_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_code TEXT NOT NULL REFERENCES customers(code),
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                total_cents INTEGER NOT NULL CHECK(total_cents>=0)
            );
            CREATE TABLE IF NOT EXISTS order_items (
                order_id INTEGER NOT NULL REFERENCES orders(id),
                sku TEXT NOT NULL REFERENCES products(sku),
                quantity INTEGER NOT NULL CHECK(quantity>0),
                unit_price_cents INTEGER NOT NULL,
                PRIMARY KEY (order_id,sku)
            );
        """)
        # Evita che un vecchio DB della demo venga riutilizzato per sbaglio.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(products)")}
        if "category" not in cols:
            raise RuntimeError("Schema database vecchio: non copiare il vecchio azienda.db. Usa data/asteria_store.db.")
        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO products VALUES (?,?,?,?,?,?)", prodotti_demo()
            )
        if conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
            zone = ["Nord-Ovest", "Nord-Est", "Centro", "Sud", "Isole"]
            clienti = [("C000", "Centro", "demo", "2026-01-01")]
            for n in range(1, 121):
                clienti.append((f"C{n:03d}", zone[(n * 7) % len(zone)],
                                "azienda" if n % 4 == 0 else "privato",
                                (datetime(2025, 11, 1) + timedelta(days=(n * 3) % 330)).date().isoformat()))
            conn.executemany("INSERT INTO customers VALUES (?,?,?,?)", clienti)
        if conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
            # Ordini storici: non riducono le giacenze iniziali, che rappresentano le scorte attuali.
            products = prodotti_demo()
            prezzo = {p[0]: p[3] for p in products}
            rng = random.Random(26)
            for numero in range(1001, 1181):
                if numero == 1001:
                    articoli = [("SKU-002", 1)]
                else:
                    codici = rng.sample(list(prezzo), rng.randint(1, 3))
                    articoli = [(c, rng.randint(1, 4)) for c in codici]
                totale = sum(prezzo[c] * q for c, q in articoli)
                giorno = datetime(2026, 1, 1, 10, tzinfo=timezone.utc) + timedelta(
                    days=rng.randrange(290), hours=rng.randrange(9))
                conn.execute("INSERT INTO orders VALUES (?,?,?,?,?)",
                             (numero, f"C{(numero - 1000) % 120 + 1:03d}", giorno.isoformat(),
                              "completato", totale))
                conn.executemany(
                    "INSERT INTO order_items VALUES (?,?,?,?)",
                    [(numero, c, q, prezzo[c]) for c, q in articoli]
                )


def euro(cents: int) -> float:
    return round(cents / 100, 2)


def list_catalog(categoria: str = "", pagina: int = 1,
                 db_path: str | Path | None = None) -> dict:
    """Elenco dei prodotti disponibili, suddiviso in pagine."""
    if type(pagina) is not int or pagina < 1:
        return {"errore": "La pagina deve essere un intero maggiore di zero."}
    if not isinstance(categoria, str):
        return {"errore": "La categoria deve essere una stringa."}
    categoria = categoria.strip()
    per_pagina = 12
    with connect(db_path) as conn:
        categorie = conn.execute(
            "SELECT category, COUNT(*) AS totale FROM products "
            "WHERE stock > 0 GROUP BY category ORDER BY category"
        ).fetchall()
        disponibili = [{"nome": c["category"], "prodotti": c["totale"]}
                       for c in categorie]
        if categoria and categoria.casefold() not in {c["nome"].casefold() for c in disponibili}:
            return {"errore": f"Categoria '{categoria}' non trovata o senza scorte.",
                    "categorie": disponibili}
        where = "WHERE stock > 0"
        params = []
        if categoria:
            where += " AND LOWER(category) = LOWER(?)"
            params.append(categoria)
        totale = conn.execute(f"SELECT COUNT(*) FROM products {where}", params).fetchone()[0]
        pagine = (totale + per_pagina - 1) // per_pagina
        if pagina > max(1, pagine):
            return {"errore": f"Pagina {pagina} non disponibile: ci sono {pagine} pagine.",
                    "totale_prodotti": totale}
        rows = conn.execute(
            f"SELECT * FROM products {where} ORDER BY sku LIMIT ? OFFSET ?",
            [*params, per_pagina, (pagina - 1) * per_pagina]
        ).fetchall()
    return {"categoria": categoria or "tutte", "totale_prodotti": totale,
            "categorie": disponibili, "pagina": pagina,
            "pagine_totali": pagine, "prodotti_per_pagina": per_pagina,
            "prodotti": [
                {"codice": r["sku"], "nome": r["name"], "categoria": r["category"],
                 "prezzo_eur": euro(r["price_cents"]), "quantita_disponibile": r["stock"]}
                for r in rows
            ]}


def search_products(query: str, db_path: str | Path | None = None) -> dict:
    if not isinstance(query, str) or not query.strip():
        return {"errore": "Inserisci una ricerca non vuota."}
    term = query.casefold().strip().rstrip(" ?!.,:;")
    richieste_generiche = {
        "prodotti", "catalogo", "magazzino", "inventario", "articoli",
        "tutti i prodotti", "elenco prodotti", "lista prodotti",
        "quali prodotti", "che prodotti ci sono in magazzino",
        "che prodotti ci sono", "cosa vendete", "cosa avete in magazzino",
        "mostrami il catalogo", "mostra catalogo",
    }
    if term in richieste_generiche:
        return list_catalog(db_path=db_path)
    for categoria in CATALOGO:
        if term in {f"prodotti {categoria.casefold()}",
                    f"articoli {categoria.casefold()}",
                    f"catalogo {categoria.casefold()}"}:
            return list_catalog(categoria=categoria, db_path=db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM products WHERE LOWER(name) LIKE ? OR LOWER(sku) LIKE ? "
            "OR LOWER(category) LIKE ? ORDER BY sku LIMIT 20",
            (f"%{term}%",) * 3,
        ).fetchall()
        approximate = False
        if not rows:
            words = re.findall(r"[\w]+", term)
            ignored = {"il", "lo", "la", "le", "gli", "i", "un", "una", "uno", "quante",
                       "quanti", "quanta", "quanto", "cerca", "trova", "disponibili",
                       "disponibile", "ci", "sono", "in", "magazzino", "vorrei"}
            words = [w for w in words if w not in ignored]
            if words:
                for row in conn.execute("SELECT * FROM products ORDER BY sku"):
                    parts = re.findall(r"[\w]+", (row["name"] + " " + row["category"]).casefold())
                    if all(any(SequenceMatcher(None, word, part).ratio() >= 0.79 for part in parts)
                           or word == row["sku"].casefold() for word in words):
                        rows.append(row)
                rows = rows[:20]
                approximate = bool(rows)
    return {
        "prodotti": [
            {"codice": r["sku"], "nome": r["name"], "categoria": r["category"],
             "prezzo_eur": euro(r["price_cents"]), "quantita_disponibile": r["stock"]}
            for r in rows
        ], "ricerca_approssimativa": approximate,
    }


def check_stock(codice: str, db_path: str | Path | None = None) -> dict:
    if not isinstance(codice, str) or not codice.strip():
        return {"errore": "Codice prodotto obbligatorio."}
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM products WHERE UPPER(sku)=?",
                           (codice.strip().upper(),)).fetchone()
    if row is None:
        return {"errore": f"Prodotto {codice} non trovato."}
    return {"codice": row["sku"], "nome": row["name"], "categoria": row["category"],
            "quantita_disponibile": row["stock"], "prezzo_eur": euro(row["price_cents"]),
            "sotto_scorta_minima": row["stock"] <= row["min_stock"]}


def get_order(numero_ordine: int, db_path: str | Path | None = None) -> dict:
    if type(numero_ordine) is not int or numero_ordine <= 0:
        return {"errore": "Il numero ordine deve essere un intero positivo."}
    with connect(db_path) as conn:
        order = conn.execute("SELECT * FROM orders WHERE id=?", (numero_ordine,)).fetchone()
        if order is None:
            return {"errore": f"Ordine {numero_ordine} non trovato."}
        items = conn.execute(
            "SELECT sku,quantity,unit_price_cents FROM order_items WHERE order_id=? ORDER BY sku",
            (numero_ordine,)).fetchall()
    return {"numero_ordine": order["id"], "data": order["created_at"],
            "stato": order["status"], "cliente": order["customer_code"],
            "totale_eur": euro(order["total_cents"]),
            "articoli": [{"codice": i["sku"], "quantita": i["quantity"],
                         "prezzo_unitario_eur": euro(i["unit_price_cents"])} for i in items]}


def create_order(codice: str, quantita: int, db_path: str | Path | None = None) -> dict:
    if not isinstance(codice, str) or not codice.strip():
        return {"errore": "Codice prodotto obbligatorio."}
    if type(quantita) is not int or not (1 <= quantita <= 50):
        return {"errore": "La quantita deve essere un intero tra 1 e 50."}
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        item = conn.execute("SELECT * FROM products WHERE UPPER(sku)=?",
                            (codice.strip().upper(),)).fetchone()
        if item is None:
            return {"errore": f"Prodotto {codice} non trovato."}
        if item["stock"] < quantita:
            return {"errore": "Scorte insufficienti", "disponibili": item["stock"]}
        price = item["price_cents"]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cursor = conn.execute(
            "INSERT INTO orders (customer_code,created_at,status,total_cents) VALUES (?,?,?,?)",
            ("C000", now, "nuovo", price * quantita))
        order_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO order_items (order_id,sku,quantity,unit_price_cents) VALUES (?,?,?,?)",
            (order_id, item["sku"], quantita, price))
        conn.execute("UPDATE products SET stock=stock-? WHERE sku=?",
                     (quantita, item["sku"]))
    return {"esito": "ordine_creato", "numero_ordine": order_id,
            "codice": item["sku"], "quantita": quantita,
            "totale_eur": euro(price * quantita)}


def statistiche(db_path: str | Path | None = None) -> dict:
    with connect(db_path) as conn:
        return {
            "prodotti": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            "categorie": conn.execute("SELECT COUNT(DISTINCT category) FROM products").fetchone()[0],
            "clienti_sintetici": conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
            "ordini": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
            "righe_ordine": conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0],
        }
