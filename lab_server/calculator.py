"""Calcolatrice sicura: espressioni aritmetiche analizzate con ast, senza eval."""

import ast
import math
import operator

MAX_LENGTH = 200
MAX_EXPONENT = 1000
MAX_RESULT = 10**100
ALLOWED_CHARS = set("0123456789.+-*/^() \t")

BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
          ast.Pow: operator.pow}
UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}

INVALID = "Espressione non valida: usa numeri, + - * / ^ e parentesi, per esempio (2 + 3) * 4."


def _checked(value):
    if isinstance(value, complex):
        raise ValueError("Il risultato non è un numero reale (es. radice di un numero negativo).")
    if (isinstance(value, float) and not math.isfinite(value)) or abs(value) > MAX_RESULT:
        raise ValueError("Risultato troppo grande: il limite è 10^100.")
    return value


def _evaluate(node: ast.AST):
    # Si accettano solo i nodi elencati: qualunque altra cosa (nomi, chiamate, attributi) è rifiutata
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return _checked(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY:
        return _checked(UNARY[type(node.op)](_evaluate(node.operand)))
    if isinstance(node, ast.BinOp) and type(node.op) in BINARY:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ValueError(f"Risultato troppo grande: l'esponente massimo è {MAX_EXPONENT}.")
        try:
            return _checked(BINARY[type(node.op)](left, right))
        except ZeroDivisionError:
            raise ValueError("Divisione per zero.") from None
        except OverflowError:
            raise ValueError("Risultato troppo grande: il limite è 10^100.") from None
    raise ValueError(INVALID)


def _format(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return repr(value) if isinstance(value, float) else str(value)


def calculate(expression: str) -> str:
    """Calcola un'espressione aritmetica; ValueError con il motivo se non è ammessa."""
    text = expression.strip()
    if not text:
        raise ValueError("Espressione vuota.")
    if len(text) > MAX_LENGTH:
        raise ValueError(f"Espressione troppo lunga: al massimo {MAX_LENGTH} caratteri.")
    if "=" in text:
        raise ValueError("Le equazioni non sono ammesse: riscrivile come espressione (es. 2x = 28 → 28 / 2).")
    for char in text:
        if char not in ALLOWED_CHARS:
            raise ValueError(f'Carattere "{char}" non ammesso: usa numeri, + - * / ^, parentesi e il punto '
                             "per i decimali.")
    try:
        tree = ast.parse(text.replace("^", "**"), mode="eval")
    except SyntaxError:
        raise ValueError(INVALID) from None
    return f"{text} = {_format(_evaluate(tree))}"
