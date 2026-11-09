import asyncio
from datetime import UTC, datetime
from typing import get_args

from fastmcp import Client

from lab_server.server import create_server
from lab_server.units import Unit

FIXED = lambda: datetime(2026, 10, 26, 13, 32, 5, tzinfo=UTC)


def call(server, action):
    """Esegue action(client) con un client MCP in memoria collegato al server."""
    async def main():
        async with Client(server) as client:
            return await action(client)
    return asyncio.run(main())


def server():
    return create_server("Europe/Rome", FIXED)


def test_catalog_lists_clock():
    tools = {t.name: t for t in call(server(), lambda c: c.list_tools())}
    assert "get_current_time" in tools
    assert "timezone" in tools["get_current_time"].inputSchema["properties"]
    assert tools["get_current_time"].description


def test_clock_call():
    result = call(server(), lambda c: c.call_tool("get_current_time", {"timezone": "Asia/Tokyo"}))
    assert result.content[0].text == "Asia/Tokyo: 2026-10-26T22:32:05+09:00"


def test_clock_unknown_timezone_is_error():
    result = call(server(), lambda c: c.call_tool("get_current_time", {"timezone": "Marte/Base"}, raise_on_error=False))
    assert result.is_error is True
    assert result.content[0].text == 'Fuso orario sconosciuto: "Marte/Base". Usa un nome IANA, es. Europe/Rome.'


def test_units_schema_is_closed_list():
    tools = {t.name: t for t in call(server(), lambda c: c.list_tools())}
    properties = tools["convert_units"].inputSchema["properties"]
    assert properties["from_unit"]["enum"] == list(get_args(Unit))
    assert properties["to_unit"]["enum"] == list(get_args(Unit))


def test_units_call():
    args = {"value": 2.5, "from_unit": "km", "to_unit": "cm"}
    assert call(server(), lambda c: c.call_tool("convert_units", args)).content[0].text == "2.5 km = 250000 cm"


def test_units_incompatible_is_error():
    args = {"value": 5, "from_unit": "km", "to_unit": "kg"}
    assert call(server(), lambda c: c.call_tool("convert_units", args, raise_on_error=False)).is_error is True


def test_units_value_as_text():
    args = {"value": "2.5", "from_unit": "km", "to_unit": "m"}
    assert call(server(), lambda c: c.call_tool("convert_units", args)).content[0].text == "2.5 km = 2500 m"


def test_units_value_with_comma_is_error():
    args = {"value": "2,5", "from_unit": "km", "to_unit": "m"}
    assert call(server(), lambda c: c.call_tool("convert_units", args, raise_on_error=False)).is_error is True


def error_text(name, args):
    result = call(server(), lambda c: c.call_tool(name, args, raise_on_error=False))
    assert result.is_error is True
    return result.content[0].text


def test_unit_not_in_list_error_is_italian():
    text = error_text("convert_units", {"value": 3, "from_unit": "KM", "to_unit": "m"})
    assert "Argomenti non validi per convert_units" in text
    assert 'from_unit: "KM" non ammesso' in text and "km" in text
    assert "pydantic" not in text and "Input should" not in text


def test_number_with_comma_error_is_italian():
    text = error_text("convert_units", {"value": "2,5", "from_unit": "km", "to_unit": "m"})
    assert 'value: "2,5" non è un numero' in text and "punto" in text


def test_missing_argument_error_is_italian():
    text = error_text("convert_units", {"value": 3, "from_unit": "km"})
    assert "to_unit: argomento mancante" in text


def test_wrong_type_error_is_italian():
    text = error_text("get_current_time", {"timezone": 5})
    assert "timezone:" in text and "Input should" not in text


def test_calculate_in_catalog_and_call():
    tools = {t.name for t in call(server(), lambda c: c.list_tools())}
    assert "calculate" in tools
    assert call(server(), lambda c: c.call_tool("calculate", {"expression": "2^5"})).content[0].text == "2^5 = 32"


def test_calculate_rejects_code():
    text = error_text("calculate", {"expression": "__import__('os')"})
    assert 'Carattere "_" non ammesso' in text


FIXED_NOV = lambda: datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


def test_catalog_has_all_nine_tools():
    names = {t.name for t in call(server(), lambda c: c.list_tools())}
    assert names == {"get_current_time", "convert_units", "calculate",
                     "date_info", "find_holiday", "add_days", "days_between",
                     "search_catalog", "get_item"}


def test_find_holiday_uses_today_in_default_timezone():
    nov = create_server("Europe/Rome", FIXED_NOV)
    text = call(nov, lambda c: c.call_tool("find_holiday", {"name": "Pasqua"})).content[0].text
    assert "già passata" in text and "2027-03-28" in text


def test_today_follows_default_timezone():
    # 2026-11-02 alle 22:00 UTC è già il 3 novembre a Tokyo
    late = create_server("Asia/Tokyo", lambda: datetime(2026, 11, 2, 22, 0, tzinfo=UTC))
    text = call(late, lambda c: c.call_tool("add_days", {"days": 0})).content[0].text
    assert "2026-11-03" in text


def test_date_info_wrong_format_is_error():
    assert "AAAA-MM-GG" in error_text("date_info", {"date": "25/12/2026"})


def test_search_catalog_schema_has_bounds():
    tools = {t.name: t for t in call(server(), lambda c: c.list_tools())}
    prop = tools["search_catalog"].inputSchema["properties"]["max_results"]
    assert prop["minimum"] == 1 and prop["maximum"] == 20 and prop["default"] == 5


def test_search_catalog_and_get_item_calls():
    found = call(server(), lambda c: c.call_tool("search_catalog", {"query": "Haskell"})).content[0].text
    assert "HS: Haskell" in found
    detail = call(server(), lambda c: c.call_tool("get_item", {"code": "hs"})).content[0].text
    assert detail.startswith("Haskell (HS)")


def test_get_item_unknown_code_is_error():
    assert "non presente nel catalogo" in error_text("get_item", {"code": "XYZ"})


def test_search_catalog_max_results_out_of_range_is_italian():
    assert error_text("search_catalog", {"query": "python", "max_results": 0}) == (
        'Argomenti non validi per search_catalog: max_results: "0" troppo piccolo (minimo 1).')
    assert "troppo grande (massimo 20)" in error_text("search_catalog", {"query": "python", "max_results": 21})


def test_search_catalog_accepts_numeric_string():
    result = call(server(), lambda c: c.call_tool("search_catalog", {"query": "python", "max_results": "10"}))
    assert result.is_error is False


def test_search_catalog_no_match_is_not_error():
    result = call(server(), lambda c: c.call_tool("search_catalog", {"query": "cobra"}))
    assert result.is_error is False
    assert result.content[0].text == (
        'Nessun linguaggio corrisponde a "cobra". Se hai usato parole al plurale riprova al singolare '
        "(es. funzionale); altrimenti il catalogo non lo contiene."
    )
