import tempfile
import unittest
from pathlib import Path

from database import check_stock, create_order, get_order, init_db, search_products


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.db"
        init_db(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_seed_is_idempotent(self):
        init_db(self.path)
        from database import statistiche
        stats = statistiche(self.path)
        self.assertEqual(stats['prodotti'], 64)
        self.assertEqual(stats['categorie'], 8)
        self.assertEqual(stats['clienti_sintetici'], 121)
        self.assertEqual(stats['ordini'], 180)
        self.assertEqual(get_order(1001, self.path)["totale_eur"], 29.9)

    def test_plural_product_search(self):
        items = search_products("tastiere", self.path)["prodotti"]
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(any(item["codice"] == "SKU-001" for item in items))
        self.assertEqual(next(item["quantita_disponibile"] for item in items if item["codice"] == "SKU-001"), 12)

    def test_nonexistent_product_is_not_confused_with_zero_stock(self):
        self.assertEqual(search_products("frigorifero", self.path)["prodotti"], [])

    def test_stock_lookup(self):
        self.assertEqual(check_stock("SKU-001", self.path)["quantita_disponibile"], 12)

    def test_elenco_catalogo_generale_e_paginazione(self):
        from database import list_catalog
        primo = list_catalog(db_path=self.path)
        self.assertEqual(primo['totale_prodotti'], 64)
        self.assertEqual(primo['pagine_totali'], 6)
        self.assertEqual(len(primo['categorie']), 8)
        self.assertEqual(len(primo['prodotti']), 12)
        secondo = list_catalog(pagina=2, db_path=self.path)
        self.assertNotEqual(primo['prodotti'][0]['codice'], secondo['prodotti'][0]['codice'])
        self.assertEqual(len(list_catalog(pagina=6, db_path=self.path)['prodotti']), 4)

    def test_elenco_catalogo_per_categoria(self):
        from database import list_catalog
        items = list_catalog('Tastiere', db_path=self.path)
        self.assertEqual(items['totale_prodotti'], 8)
        self.assertTrue(all(p['categoria'] == 'Tastiere' for p in items['prodotti']))
        self.assertIn('errore', list_catalog('NonEsiste', db_path=self.path))
        self.assertIn('errore', list_catalog(pagina=0, db_path=self.path))

    def test_ricerche_generiche_mostrano_catalogo(self):
        for query in ('prodotti', 'catalogo', 'che prodotti ci sono in magazzino?'):
            result = search_products(query, self.path)
            self.assertEqual(result['totale_prodotti'], 64)
            self.assertEqual(len(result['categorie']), 8)
        self.assertEqual(search_products('prodotti audio', self.path)['totale_prodotti'], 8)

    def test_prodotti_esauriti_esclusi_dal_catalogo(self):
        from database import list_catalog
        from database import connect
        with connect(self.path) as conn:
            conn.execute("UPDATE products SET stock=0 WHERE sku='SKU-001'")
        self.assertEqual(list_catalog(db_path=self.path)['totale_prodotti'], 63)

    def test_order_writes_stock_atomically(self):
        result = create_order("SKU-001", 2, self.path)
        self.assertEqual(result["esito"], "ordine_creato")
        self.assertEqual(result["totale_eur"], 159.8)
        self.assertEqual(check_stock("SKU-001", self.path)["quantita_disponibile"], 10)
        self.assertEqual(get_order(result["numero_ordine"], self.path)["articoli"][0]["quantita"], 2)

    def test_insufficient_stock_does_not_change_db(self):
        result = create_order("SKU-001", 13, self.path)
        self.assertIn("errore", result)
        self.assertEqual(check_stock("SKU-001", self.path)["quantita_disponibile"], 12)

    def test_catalogo_e_ordini_sintetici(self):
        from database import statistiche
        import sqlite3
        stats = statistiche(self.path)
        self.assertEqual(stats['prodotti'], 64)
        self.assertEqual(stats['categorie'], 8)
        self.assertEqual(stats['clienti_sintetici'], 121)
        self.assertEqual(stats['ordini'], 180)
        conn = sqlite3.connect(self.path)
        try:
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])
        finally:
            conn.close()

    def test_secondo_avvio_non_cancella_ordini_creati(self):
        primo = create_order('SKU-001', 1, self.path)
        init_db(self.path)
        self.assertEqual(check_stock('SKU-001', self.path)['quantita_disponibile'], 11)
        self.assertEqual(get_order(primo['numero_ordine'], self.path)['totale_eur'], 79.9)

    def test_invalid_quantities(self):
        for q in (-1, 0, 2.5, "2", True, 51):
            self.assertIn("errore", create_order("SKU-001", q, self.path))


if __name__ == "__main__":
    unittest.main()
