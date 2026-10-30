"""Server MCP locale su stdio: nessun hosting e nessuna porta pubblica."""

from mcp.server import MCPServer

from database import check_stock, create_order, get_order, init_db, list_catalog, search_products

mcp = MCPServer("Asteria Store MCP")


@mcp.tool()
def cerca_prodotti(query: str) -> dict:
    """Cerca un prodotto specifico per nome, categoria o SKU. Per elenchi generali usa elenca_catalogo."""
    return search_products(query)


@mcp.tool()
def elenca_catalogo(categoria: str = "", pagina: int = 1) -> dict:
    """Elenca prodotti in magazzino, con categorie, quantità, prezzi e pagine da 12 prodotti. Categoria facoltativa."""
    return list_catalog(categoria, pagina)


@mcp.tool()
def verifica_disponibilita(codice: str) -> dict:
    """Mostra prezzo e quantita' attualmente disponibili per un codice SKU."""
    return check_stock(codice)


@mcp.tool()
def consulta_ordine(numero_ordine: int) -> dict:
    """Recupera i dettagli di un ordine dato il suo numero; solo lettura."""
    return get_order(numero_ordine)


@mcp.tool()
def crea_ordine(codice: str, quantita: int) -> dict:
    """CREA UN ORDINE E SCALA LE SCORTE. Richiede sempre conferma prima della chiamata."""
    return create_order(codice, quantita)


if __name__ == "__main__":
    init_db()
    mcp.run()  # trasporto stdio: avviato automaticamente dal client locale
