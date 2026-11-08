"""Server MCP: registra gli strumenti del laboratorio con FastMCP."""

import logging
from collections.abc import Callable
from datetime import datetime

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from lab_server.calculator import calculate as evaluate
from lab_server.clock import current_time, utc_now
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

    return mcp
