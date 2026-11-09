"""Errori di validazione degli argomenti in italiano, per tutti gli strumenti del server."""

import pydantic
from fastmcp.exceptions import ToolError, ValidationError
from fastmcp.server.middleware import Middleware

NUMBER_ERRORS = {"float_parsing", "float_type", "int_parsing", "int_type", "int_from_float"}


def _describe(error: dict) -> str:
    field = str(error["loc"][0]) if error["loc"] else "argomenti"
    kind, value = error["type"], error.get("input")
    if kind in ("missing", "missing_argument"):
        return f"{field}: argomento mancante"
    if kind == "unexpected_keyword_argument":
        return f"{field}: argomento non previsto"
    if kind == "literal_error":
        allowed = error.get("ctx", {}).get("expected", "").replace("'", "").replace(" or ", ", ")
        return f'{field}: "{value}" non ammesso; valori ammessi: {allowed}'
    if kind in NUMBER_ERRORS:
        whole = "intero " if kind.startswith("int") else ""
        return f'{field}: "{value}" non è un numero {whole}(usa il punto per i decimali)'
    if kind == "greater_than_equal":
        return f'{field}: "{value}" troppo piccolo (minimo {error["ctx"]["ge"]})'
    if kind == "less_than_equal":
        return f'{field}: "{value}" troppo grande (massimo {error["ctx"]["le"]})'
    if kind == "string_type":
        return f"{field}: deve essere un testo"
    return f'{field}: valore "{value}" non valido'


def describe_validation_error(tool: str, error: pydantic.ValidationError) -> str:
    parts = {}
    for detail in error.errors(include_url=False):
        # Con un tipo unione (es. str | None) pydantic dà un errore per ogni alternativa: ne basta uno per campo
        field = detail["loc"][0] if detail["loc"] else None
        parts.setdefault(field, _describe(detail))
    return f"Argomenti non validi per {tool}: {'; '.join(parts.values())}."


class ItalianValidationErrors(Middleware):
    """FastMCP valida gli argomenti con pydantic prima di chiamare il tool: traduce quei messaggi (inglesi)."""

    async def on_call_tool(self, context, call_next):
        try:
            return await call_next(context)
        except ValidationError as error:
            if isinstance(error.__cause__, pydantic.ValidationError):
                raise ToolError(describe_validation_error(context.message.name, error.__cause__)) from None
            raise
