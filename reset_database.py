"""Ripristina il database. Prima crea una copia con data e ora."""

from datetime import datetime
from pathlib import Path
import shutil
from database import DEFAULT_DB, init_db, statistiche


def main():
    path = Path(DEFAULT_DB)
    print("Database:", path)
    print("L'operazione cancella dal database attivo gli ordini creati nelle prove.")
    risposta = input("Scrivi RIPRISTINA per confermare: ").strip()
    if risposta != "RIPRISTINA":
        print("Annullato.")
        return
    if path.exists():
        dest = path.with_name("backup_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".db")
        shutil.copy2(path, dest)
        path.unlink()
        print("Copia del vecchio database:", dest)
    init_db()
    print("Dati ripristinati:", statistiche())


if __name__ == "__main__":
    main()
