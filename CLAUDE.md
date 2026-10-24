# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AI Technical Watch ("Veille IA"): FastAPI backend + React/Vite frontend that triggers LLM-generated (Codex by default) technical-watch reports, stores them in SQLite, and exposes summaries, per-extract detail expansion, notes, chat-over-reports, and PDF export.

## Commands

Local dev (one shot, both stacks): `./dev.sh` from repo root. Creates `backend/venv`, installs deps, runs `uvicorn app.main:app --reload --port 8000` and `npm run dev` (Vite on 5173).

Backend only — from `backend/`:
- Run: `source venv/bin/activate && uvicorn app.main:app --reload`
- Install deps: `pip install -r requirements.txt`
- Tests: `pytest` from repo root (`test_llm_providers.py`, `test_news_items.py`, `test_prompts_renderer.py`; `conftest.py` isolates the DB in `test_app.db`). No suite under `backend/`.

Frontend only — from `frontend/`:
- Dev: `npm run dev`
- Build (typecheck + bundle): `npm run build` — runs `tsc -b` then `vite build`. Use this to typecheck.
- Lint: `npm run lint`

Containers: `podman-compose up --build` (also works with `docker compose`). Mounts `./data` for the SQLite DB and `./backend/app` for hot reload.

## Architecture

**Backend (`backend/app/`)** — single-file FastAPI app:
- `main.py` holds endpoints, LLM provider dispatch, prompt strings, and PDF rendering. Most logic lives here; do not split prematurely.
- `models.py` / `schemas.py` / `database.py` are SQLAlchemy ORM, Pydantic, and engine setup. SQLite at `backend/sql_app.db` (or `DATABASE_URL` env, e.g. `./data/sql_app.db` in container).
- Schema is created via `models.Base.metadata.create_all` on import. Lightweight in-place migrations live in `ensure_reports_schema()` (called at import). Add new column migrations there rather than introducing Alembic unless the user asks.
- Tables: `reports` (typed via `report_type`, default `technical_watch`), `report_summaries` (1:1 with report), `notes` (highlights/annotations), `chat_messages` (history with serialized `report_ids` JSON column), `news_items` (one row per « Nouveautés détaillées » entry; saved items survive report deletion with `report_id` set to NULL).

**LLM providers** — selected by `LLM_PROVIDER` env (`codex` default, `openrouter`, `gemini`). `generate_llm_content(prompt, timeout_seconds, web_search=False)` is the single dispatch point — call it (preceded by `ensure_llm_ready()`) instead of touching a backend directly.
1. `codex` (default): shells out to `codex exec --skip-git-repo-check --ephemeral --sandbox read-only -o <tmpfile> -c web_search="live"|"disabled" -`, prompt on stdin (reports exceed the per-argument size limit), answer read from the `-o` file. Auth comes from `codex login` (`~/.codex`). Optional `CODEX_MODEL`, `CODEX_REASONING_EFFORT`, `CODEX_BIN`, `CODEX_WEB_SEARCH` (default true). Only `/reports/trigger` asks for web search.
2. `openrouter`: OpenAI-compatible `POST /api/v1/chat/completions` via httpx with `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` (default `openrouter/auto`). No internet access unless `OPENROUTER_WEB_SEARCH=true` (paid `web` plugin) — without it the daily watch relies on model knowledge only.
3. `gemini` (legacy): CLI backend (`gemini --output-format json`, when `~/.gemini/oauth_creds.json` and `gemini` on PATH exist; model mapped through `CLI_MODEL_ALIASES`) or `google.generativeai` SDK via OAuth creds / `GEMINI_API_KEY`. In containers the OAuth refresh needs `GEMINI_OAUTH_CLIENT_ID` / `GEMINI_OAUTH_CLIENT_SECRET`. Google SDK modules (`google.generativeai`, `google.auth`, `google.oauth2`) are imported lazily (`import_genai()` and local imports) so they never load with Codex/OpenRouter — keep them out of module-level imports.

Timeouts: `LLM_TIMEOUT_SECONDS` (default 90) and `LLM_REPORT_TIMEOUT_SECONDS` (default 600, used for the watch and CODIR note). The backend Dockerfile installs `@openai/codex`; `podman-compose.yml` mounts `${HOME}/.codex` read-write so token refresh works.

**Auth on the API** — `verify_token` is a `Security(HTTPBearer)` dep applied to every endpoint. It is a no-op when `API_TOKEN` env is unset (dev default). When set, every request needs `Authorization: Bearer <API_TOKEN>`. Note: `frontend/src/api.ts` does NOT send this header anywhere — if you set `API_TOKEN` in backend, the frontend currently breaks until you add an axios interceptor.

**CORS** — driven by `ALLOWED_ORIGINS` env (comma-separated, default `http://localhost:5173`). `allow_credentials=False`, so don't switch the frontend to cookie auth without flipping that.

**Prompts** — `TECHNICAL_PROMPT` (large French prompt for daily watch generation; always sent through `build_technical_prompt(db)`, which prepends today's date and the covered 24h window in Europe/Paris and appends the titles of recent `news_items` as « Déjà couvert » to avoid repeats). Chat uses `build_chat_prompt()` with full report content + summary + notes (`build_report_chat_context`), the last 6 conversation messages sent by the frontend, and an optional `web_search` flag (rejected with 400 when the provider has no web access; see `GET /llm/info`). `persist=false` keeps technical calls (dashboard project synthesis) out of chat history. Summary/detail/definition prompts stay inline in their endpoints. They are intentionally written in French; preserve the language and section headings (`## 1. Nouveautés majeures`, etc.) since the PDF renderer (`build_pdf_story`) and frontend markdown layout key off `## ` / `- ` / `|` line prefixes.

**Daily run & newsletter** — `POST /cron/daily` (for an external cron; `?force=true` regenerates) creates today's watch (Europe/Paris date) only if none exists, and returns `newsletter_url`. `/reports/trigger` and the cron share `generate_watch_report()` and `WATCH_GENERATION_LOCK` (409 when a run is in progress); both are sync `def` so the multi-minute LLM call runs in FastAPI's threadpool instead of blocking the event loop — keep LLM-calling endpoints sync. `GET /reports/{id}/newsletter` renders the report deterministically (no LLM) through `backend/app/newsletter.py` into a mail-safe HTML body: starts with `<table>`, tables only, inline styles, `bgcolor` + `background-color` pairs, 4px bar cells instead of `border-left`, ASCII-only via HTML entities, 720px, Cowork colour code (header `#0f2740`, summary `#eef4f9`, rules `#2f8fd6`, security `#fdf5f4`/`#c0392b`, per-actor bar colours in `ACTORS`). `test_newsletter.py` guards these constraints. Nothing is emailed yet.

**PDF export** — pure ReportLab via `build_pdf_story()`. It hand-parses the markdown subset the prompt produces (h2, bullets, tables, images). Keep generated content within that subset; do not introduce nested lists, h3, or fenced code blocks without extending the renderer.

**Frontend (`frontend/src/`)**:
- `App.tsx` is the single-page UI (~25k chars) — sidebar of reports, main pane with markdown render, summary, notes, chat. Edit in place rather than splitting into many small components unless the user asks.
- `api.ts` hardcodes `API_URL = 'http://localhost:8000'`. The container compose passes `VITE_API_URL` but it is not read — wire it in if running non-locally.
- React 19 + Vite 8 + react-markdown + remark-gfm. Dark-tech visual theme owned by `App.css` and `index.css` (mouse-tracking gradient, scan line, grid background — see commits and `docs/superpowers/specs/2026-04-01-dark-tech-redesign-design.md`).

## Conventions

- All user-facing copy and prompt content is French. Match the surrounding language when editing prompts or UI strings.
- Backend endpoints follow REST under resource paths (`/reports`, `/reports/{id}/summary`, `/reports/{id}/notes`, `/chat`, `/chat/messages`). New endpoints should accept `_=Depends(verify_token)` to stay protected when `API_TOKEN` is set.
- When adding a column, also extend `ensure_reports_schema()` (or write a sibling helper) so existing dev DBs migrate on next boot.
- `sql_app.db` is committed locally; treat it as throwaway dev state, not fixtures.
