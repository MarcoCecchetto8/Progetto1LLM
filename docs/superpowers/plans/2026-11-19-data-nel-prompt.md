# Data di oggi nel messaggio di sistema — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a ogni chiamata al modello dell'agente e a ogni giudizio del revisore arriva una riga con la data di oggi (giorno della settimana, data in parole e AAAA-MM-GG, fuso), calcolata al momento della chiamata.

**Architecture:** una funzione pura compone la riga; il grafo la aggiunge al messaggio di sistema solo per la chiamata (come `with_summary`, prima del riassunto); il revisore la mette in testa alla richiesta. Entrambi ricevono una funzione senza argomenti che restituisce la riga, costruita in `agent_service/startup.py` con il fuso delle preferenze. Senza quella funzione tutto resta com'è.

**Tech Stack:** Python, LangGraph, pytest.

**Spec:** `docs/superpowers/specs/2026-11-19-data-nel-prompt-design.md`

## Global Constraints

- Branch `feature/data-nel-prompt` da `developer`; Conventional Commits in italiano con la riga ESATTA `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; `git status`, controllo del diff, staging selettivo; nessun push. Non leggere né toccare `lezione-03/`.
- Test senza LM Studio; suite completa verde (`.venv/Scripts/python.exe -m pytest`, controllare l'exit code) prima di ogni commit.
- Testo esatto della riga: `Oggi è {giorno} {g} {mese} {aaaa} ({AAAA-MM-GG}), fuso orario {fuso}.` con giorno e mese in italiano minuscolo, giorno del mese senza zero iniziale, es. `Oggi è giovedì 19 novembre 2026 (2026-11-19), fuso orario Europe/Rome.` Nomi da tabelle nel codice, mai da `locale`/`strftime`.
- Solo la data, mai l'ora. Testi esistenti del messaggio di sistema, del revisore e del router invariati. La riga non entra mai nella cronologia.
- Router invariato.

## Review Focus

1. Agente acceso a cavallo della mezzanotte: la riga si calcola a ogni chiamata, non all'avvio (test con orologio che cambia fra due turni dello stesso grafo, Task 1).
2. Turno con riassunto: la riga sta prima dell'intestazione del riassunto, che resta l'ultima parte del messaggio di sistema (test, Task 1).
3. Nuovo tentativo dopo il revisore e più passaggi con strumenti nello stesso turno: ogni chiamata al modello ha la riga, la cronologia mai (test, Task 1).
4. Grafo o revisore costruiti senza la funzione della data (test esistenti, CLI dei test): comportamento identico a oggi (test, Task 1).
5. Fuso delle preferenze diverso da Europe/Rome (es. America/New_York vicino a mezzanotte): la data è quella del fuso delle preferenze, non del sistema (test, Task 2).

---

### Task 1: Riga della data, grafo e revisore

**Files:**
- Modify: `assistant/graph.py` (nuova `today_line`, nuova `with_today`, parametro di `build_graph`, chiamata in `model_node`)
- Modify: `assistant/reviewer.py` (parametro di `build_reviewer`)
- Test: `tests/test_graph.py`, `tests/test_reviewer.py`

**Interfaces:**
- Produces:
  - `today_line(day: datetime.date, timezone: str) -> str` in `assistant/graph.py` (testo esatto nei Global Constraints; tabelle `_GIORNI` lunedì…domenica indicizzate con `day.weekday()`, `_MESI` gennaio…dicembre).
  - `with_today(messages: list[AnyMessage], line: str) -> list[AnyMessage]` in `assistant/graph.py`: copia della lista con `"\n\n" + line` aggiunto al primo `SystemMessage` (stesso schema di `with_summary`); con `line == ""` restituisce la lista stessa.
  - `build_graph(..., today: Callable[[], str] | None = None)`: in `model_node` la chiamata diventa `with_summary(with_today(messages, today() if today else ""), summary)`.
  - `build_reviewer(model, today: Callable[[], str] | None = None)`: se presente, la richiesta di giudizio è `today() + "\n\n" + review_request(...)`.

- [ ] **Step 1: test che falliscono**

```python
# tests/test_graph.py
def test_today_line_italian():
    assert today_line(date(2026, 11, 19), "Europe/Rome") == \
        "Oggi è giovedì 19 novembre 2026 (2026-11-19), fuso orario Europe/Rome."
    assert today_line(date(2027, 1, 3), "Asia/Tokyo") == \
        "Oggi è domenica 3 gennaio 2027 (2027-01-03), fuso orario Asia/Tokyo."

def test_with_today_only_for_call():
    messages = [SystemMessage("s"), HumanMessage("q")]
    assert with_today(messages, "") is messages
    result = with_today(messages, "Oggi è X.")
    assert result[0].content == "s\n\nOggi è X." and messages[0].content == "s"
```

  e, con il modello `Recording` di `test_model_receives_summary_in_system_prompt`:
  - `test_model_receives_today_line`: `build_graph(..., today=lambda: "Oggi è X.")` → `seen[0][0].content == "s\n\nOggi è X."`; `out["messages"][0].content == "s"`;
  - `test_today_line_before_summary`: con `state["summary"] = "R"` → `seen[0][0].content == f"s\n\nOggi è X.\n\n{AGENT_SUMMARY_HEADER}\nR"`;
  - `test_today_line_on_every_call`: modello `tool_call({}, "a")` poi `AIMessage("ok")` → entrambe le chiamate in `seen` hanno la riga; nessun messaggio di `out["messages"]` la contiene;
  - `test_today_line_follows_the_clock`: `today` restituisce da una lista `["Oggi è A.", "Oggi è B."]`; due `invoke` dello stesso grafo → prima chiamata con «A», seconda con «B»;
  - `test_without_today_unchanged`: senza `today` → `seen[0][0].content == "s"`.

```python
# tests/test_reviewer.py
def test_build_reviewer_with_today():
    model = FakeModel()
    build_reviewer(model, today=lambda: "Oggi è X.")("domanda", "risposta")
    assert model.invoked[1] == HumanMessage("Oggi è X.\n\n" + review_request("domanda", "risposta"))
```
  (`test_build_reviewer` esistente resta invariato: senza `today` la richiesta è identica.)

- [ ] **Step 2:** `.venv/Scripts/python.exe -m pytest tests/test_graph.py tests/test_reviewer.py -q` → i nuovi test FAIL.
- [ ] **Step 3:** implementare le interfacce sopra.
- [ ] **Step 4:** stessi test → PASS; suite completa verde.
- [ ] **Step 5: commit** `feat(grafo): data di oggi nel messaggio di sistema e nella richiesta del revisore`

---

### Task 2: Collegamento nell'avvio dell'agente

**Files:**
- Modify: `agent_service/startup.py` (passare la funzione della data a `build_graph` e a `build_reviewer`)
- Modify: `README.md` (sezione del messaggio di sistema / preferenze: la riga, perché, solo data non ora; misura «prima e dopo» da compilare)
- Test: `tests/test_agent_startup.py`

**Interfaces:**
- Consumes: `today_line`, `build_graph(..., today=...)`, `build_reviewer(model, today=...)` del Task 1.
- Produces: in `build_agent`, accanto al `today` già presente, `date_line = lambda: today_line(datetime.now(zone).date(), preferences.fuso_orario)` passata come `today=` a entrambi.

- [ ] **Step 1: test che fallisce.** Estrarre la costruzione della funzione in `def date_line_for(zone_name: str, now: Callable[[ZoneInfo], datetime] = datetime.now) -> Callable[[], str]` in `agent_service/startup.py`, così il fuso è testabile senza avviare l'agente:

```python
def test_date_line_uses_preferences_timezone():
    utc = datetime(2026, 11, 20, 3, 30, tzinfo=timezone.utc)   # a New York è ancora il 19
    line = date_line_for("America/New_York", now=lambda zone: utc.astimezone(zone))()
    assert line == "Oggi è giovedì 19 novembre 2026 (2026-11-19), fuso orario America/New_York."
```

  Il passaggio della funzione a grafo e revisore si verifica leggendo il diff (il comportamento del grafo con la riga è coperto dal Task 1).
- [ ] **Step 2:** `.venv/Scripts/python.exe -m pytest tests/test_agent_startup.py -q -k date_line` → FAIL.
- [ ] **Step 3:** implementare `date_line_for` e passarla in `build_agent` (`build_graph(..., today=date_line)`, `build_reviewer(chat_model, today=date_line)`).
- [ ] **Step 4:** PASS; suite completa verde.
- [ ] **Step 5:** README: descrivere la riga (esempio esatto), che si calcola a ogni chiamata nel fuso delle preferenze, che arriva ad agente e revisore e non al router, che l'ora resta allo strumento; tabella «Misura della data (lfm2)» con le colonne prima/dopo e le righe delle 4 domande lasciate «da compilare» (le compila il controller dopo la misura).
- [ ] **Step 6: commit** `feat(agente): data di oggi nel fuso delle preferenze a ogni chiamata`
