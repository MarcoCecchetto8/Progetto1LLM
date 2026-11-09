"""Server MCP: registra gli strumenti del laboratorio con FastMCP."""

import logging
from collections.abc import Callable
from datetime import date, datetime
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from lab_server.calculator import calculate as evaluate
from lab_server import catalog, dates
from lab_server.catalog import DEFAULT_RESULTS, MAX_RESULTS
from lab_server.clock import current_time, utc_now
from lab_server.timezones import get_timezone
from lab_server.units import Unit, convert
from lab_server.validation import ItalianValidationErrors

logger = logging.getLogger("lab_server")


def create_server(default_timezone: str, now: Callable[[], datetime] = utc_now) -> FastMCP:
    mcp = FastMCP("Strumenti del laboratorio", middleware=[ItalianValidationErrors()])

    @mcp.tool
    def get_current_time(timezone: str | None = None) -> str:
        """Restituisce data e ora attuali in un fuso orario.

        Il parametro timezone è un nome IANA (es. Europe/Rome, Asia/Tokyo).
        Se omesso, si usa il fuso orario predefinito.
        """
        try:
            result = current_time(timezone, default_timezone, now)
        except ValueError as error:
            # ToolError: il client riceve un errore MCP, non un risultato di successo
            raise ToolError(str(error)) from None
        logger.debug("get_current_time(timezone=%s) → %s", timezone, result)
        return result

    @mcp.tool
    def convert_units(value: float, from_unit: Unit, to_unit: Unit) -> str:
        """Converte un valore fra due unità della stessa categoria.

        Categorie e unità ammesse:
        - lunghezza: mm, cm, dm, m, dam, hm, km
        - peso: mg, cg, dg, g, dag, hg, kg, q (quintale), t (tonnellata)
        - volume: ml, cl, dl, l, dal, hl, m3 (metro cubo)
        - temperatura: C (gradi Celsius), K (kelvin)
        Non si può convertire fra categorie diverse (es. km in kg).
        """
        try:
            result = convert(value, from_unit, to_unit)
        except ValueError as error:
            raise ToolError(str(error)) from None
        logger.debug("convert_units(%s, %s, %s) → %s", value, from_unit, to_unit, result)
        return result

    @mcp.tool
    def calculate(expression: str) -> str:
        """Calcola un'espressione aritmetica in modo sicuro.

        Ammessi: numeri (decimali con il punto), + - * /, parentesi, potenza con ^ o **.
        Non ammessi: lettere, funzioni (es. sqrt) ed equazioni con = (riscrivile come espressione).
        """
        try:
            result = evaluate(expression)
        except ValueError as error:
            raise ToolError(str(error)) from None
        logger.debug("calculate(%s) → %s", expression, result)
        return result

    def today() -> date:
        return now().astimezone(get_timezone(default_timezone)).date()

    def run(label: str, action) -> str:
        try:
            result = action()
        except ValueError as error:
            raise ToolError(str(error)) from None
        logger.debug("%s → %s", label, result)
        return result

    @mcp.tool
    def date_info(date: str) -> str:
        """Giorno della settimana di una data e, se lo è, la festività; dice se la data è passata, oggi o futura.

        date: data nel formato AAAA-MM-GG (es. 2026-12-25).
        """
        return run(f"date_info({date})", lambda: dates.date_info(date, today()))

    @mcp.tool
    def find_holiday(name: str, year: int | None = None) -> str:
        """Data e giorno della settimana di una festività nazionale italiana (es. Natale, Pasqua, Pasquetta).

        Senza year si usa l'anno corrente; se quest'anno la festività è già passata lo segnala e dà la prossima.
        """
        return run(f"find_holiday({name}, {year})", lambda: dates.find_holiday(name, year, today()))

    @mcp.tool
    def add_days(days: int, start: str | None = None) -> str:
        """Data che si ottiene aggiungendo (o togliendo, se negativo) un numero di giorni.

        start: data di partenza AAAA-MM-GG; se omessa si parte da oggi.
        """
        return run(f"add_days({days}, {start})", lambda: dates.add_days(days, start, today()))

    @mcp.tool
    def days_between(end: str, start: str | None = None) -> str:
        """Numero di giorni fra due date AAAA-MM-GG (es. quanti giorni mancano a una scadenza).

        start: data di partenza; se omessa si parte da oggi.
        """
        return run(f"days_between({end}, {start})", lambda: dates.days_between(end, start, today()))

    @mcp.tool
    def search_catalog(query: str, max_results: Annotated[int, Field(ge=1, le=MAX_RESULTS)] = DEFAULT_RESULTS) -> str:
        """Cerca linguaggi di programmazione nel catalogo per parole chiave (nome, autore, paradigma, anno, parole della descrizione).

        Passare poche parole al singolare (es. funzionale, Haskell, Bell Labs).
        Restituisce un elenco breve con codice, nome e anno e il numero totale trovato; usarlo quando non si conosce il codice.
        """
        return run(f"search_catalog({query}, {max_results})", lambda: catalog.search(query, max_results))

    @mcp.tool
    def get_item(code: str) -> str:
        """Tutte le informazioni di un solo linguaggio dato il suo codice (es. PY, HS), ottenuto da search_catalog."""
        return run(f"get_item({code})", lambda: catalog.get_item(code))

    return mcp
