# Barra laterale richiudibile — piano

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ☰ sempre visibile; a finestra larga apre/chiude la barra delle chat (scelta ricordata); fino a 1000 px la barra si chiude da sola e ☰ la apre come pannello.

**Architecture:** solo front-end statico: `frontend_service/static/style.css` (classe `body.rail-closed`, media query del pannello a 1000 px) e `frontend_service/static/app.js` (gestore del pulsante). Nessun cambio di API né di Python.

**Spec:** `docs/superpowers/specs/2026-11-25-frontend-chat-design.md`, sez. 5, revisione «barra laterale richiudibile».

## Global Constraints

- Branch `feature/barra-laterale` da `developer`; Conventional Commits in italiano.
- `localStorage` sempre dentro `try/catch` (come `pico.misure`).
- Nessun font o script esterno.

## Review Focus

- Finestra ridimensionata da larga a stretta con la barra chiusa: il pannello deve aprirsi con ☰ (la classe `rail-closed` non deve nasconderlo).
- Da stretta a larga con il pannello aperto: niente sfondo scuro rimasto.
- Primo avvio senza valore salvato: barra aperta.

---

### Task 1: barra richiudibile

**Files:** Modify `frontend_service/static/style.css`, `frontend_service/static/app.js`

- [ ] **Step 1: CSS.** `.menu` visibile sempre (stesso aspetto di oggi nel pannello stretto); `body.rail-closed { grid-template-columns: minmax(0, 1fr); }` e `body.rail-closed .rail { display: none; }` solo in `@media (min-width: 1001px)`; spostare in `@media (max-width: 1000px)` le regole di `body` (una colonna), `.rail` (pannello), `body.menu-open .rail`, `.scrim` e la visibilità/transizione della barra chiusa; il resto resta in `@media (max-width: 860px)`.
- [ ] **Step 2: JS.** `const NARROW = window.matchMedia("(max-width: 1000px)")`; `RAIL_KEY = "pico.barra"`; `railClosedSaved() -> boolean` e `saveRail(closed: boolean)` con `try/catch`; `syncMenuButton()` aggiorna `aria-expanded` e il testo nascosto («Nascondi le chat»/«Mostra le chat») secondo lo stato visibile; il clic su ☰: stretta → comportamento di oggi (`menu-open`), larga → alterna `rail-closed` e salva; all'avvio applicare `rail-closed` dal valore salvato; `NARROW.addEventListener("change", …)` chiude il pannello (`closeMenu`) e richiama `syncMenuButton`.
- [ ] **Step 3: verifica.** `node --check frontend_service/static/app.js`; `python -m pytest tests/test_frontend_service.py -q` → passano; screenshot headless a 1400 px e 700 px; prova dell'utente nel browser (chiudi/apri a finestra larga, ricarica, rimpicciolisci sotto 1000 px, ☰ apre il pannello, ingrandisci di nuovo).
- [ ] **Step 4: commit** `feat(frontend): barra laterale richiudibile anche a finestra larga`; README (sezione Front-end) aggiornato nello stesso task; merge `--no-ff` in `developer` e push dopo la prova dell'utente.
