"""Crea il database sintetico del negozio, se non esiste."""

from database import DEFAULT_DB, init_db, statistiche


def main():
    init_db()
    stats = statistiche()
    print("\nAsteria Store - database pronto")
    print("Percorso:", DEFAULT_DB)
    print("Prodotti:", stats["prodotti"], "| Categorie:", stats["categorie"])
    print("Clienti fittizi:", stats["clienti_sintetici"])
    print("Ordini storici e nuovi:", stats["ordini"])
    print("Righe ordine:", stats["righe_ordine"])
    print("Tutti i dati sono sintetici.\n")


if __name__ == "__main__":
    main()
