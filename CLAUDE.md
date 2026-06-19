# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AI Technical Watch ("Veille IA"): FastAPI backend + React/Vite frontend that triggers Gemini-generated technical-watch reports, stores them in SQLite, and exposes summaries, per-extract detail expansion, notes, chat-over-reports, and PDF export.

## Commands

Local dev (one shot, both stacks): `./dev.sh` from repo root. Creates `backend/venv`, installs deps, runs `uvicorn app.main:app --reload --port 8000` and `npm run dev` (Vite on 5173).

Backend only — from `backend/`:
- Run: `source venv/bin/activate && uvicorn app.main:app --reload`
- Install deps: `pip install -r requirements.txt`
- Tests: `pytest` (test files at repo root: `test_gemini_auth.py`, `list_models.py`). No suite under `backend/`.

Frontend only — from `frontend/`:
- Dev: `npm run dev`
- Build (typecheck + bundle): `npm run build` — runs `tsc -b` then `vite build`. Use this to typecheck.
- Lint: `npm run lint`

Containers: `podman-compose up --build` (also works with `docker compose`). Mounts `./data` for the SQLite DB and `./backend/app` for hot reload.

## Architecture

**Backend (`backend/app/`)** — single-file FastAPI app:
- `main.py` holds endpoints, Gemini auth + dispatch, prompt strings, and PDF rendering. Most logic lives here; do not split prematurely.
- `models.py` / `schemas.py` / `database.py` are SQLAlchemy ORM, Pydantic, and engine setup. SQLite at `backend/sql_app.db` (or `DATABASE_URL` env, e.g. `./data/sql_app.db` in container).
- Schema is created via `models.Base.metadata.create_all` on import. Lightweight in-place migrations live in `ensure_reports_schema()` (called at import). Add new column migrations there rather than introducing Alembic unless the user asks.
- Tables: `reports` (typed via `report_type`, default `technical_watch`), `report_summaries` (1:1 with report), `notes` (highlights/annotations), `chat_messages` (history with serialized `report_ids` JSON column).

**Gemini integration** — two interchangeable backends, selected at call time by `should_use_gemini_cli_backend()`:
1. CLI backend: shells out to the `gemini` binary with `--output-format json` when both `~/.gemini/oauth_creds.json` AND `gemini` on PATH exist. Model name is mapped through `CLI_MODEL_ALIASES` (e.g. `gemini-2.0-flash-lite` → `auto-gemini-3`).
2. SDK backend: `google.generativeai` via OAuth creds (refreshed in-process with `extract_gemini_cli_oauth_client_config()` scraping the CLI's bundled `oauth2.js` for client_id/secret) or `GEMINI_API_KEY` fallback.

OAuth-scrape path only works when the `gemini` CLI is installed on the host running the backend. In containers the `gemini` binary is absent, so `extract_gemini_cli_oauth_client_config()` returns `(None, None)`. `podman-compose.yml` therefore mounts `${HOME}/.gemini:/root/.gemini:ro` and reads `backend/.env` — refresh requires `GEMINI_OAUTH_CLIENT_ID` / `GEMINI_OAUTH_CLIENT_SECRET` to be set there. Without those, the access_token works only until expiry (~1h) and refresh fails. Alternative: set `GEMINI_API_KEY` in `backend/.env` and skip OAuth entirely. For the full CLI backend in-container, also install `@google/gemini-cli` in the backend Dockerfile so `shutil.which("gemini")` resolves.

`generate_gemini_content()` is the single dispatch point — call it instead of touching either backend directly. SDK calls run through `GEMINI_EXECUTOR` (ThreadPoolExecutor) with hard timeout `GEMINI_TIMEOUT_SECONDS` (default 90).

**Auth on the API** — `verify_token` is a `Security(HTTPBearer)` dep applied to every endpoint. It is a no-op when `API_TOKEN` env is unset (dev default). When set, every request needs `Authorization: Bearer <API_TOKEN>`. Note: `frontend/src/api.ts` does NOT send this header anywhere — if you set `API_TOKEN` in backend, the frontend currently breaks until you add an axios interceptor.

**CORS** — driven by `ALLOWED_ORIGINS` env (comma-separated, default `http://localhost:5173`). `allow_credentials=False`, so don't switch the frontend to cookie auth without flipping that.

**Prompts** — `TECHNICAL_PROMPT` (large French prompt for daily watch generation), plus inline summary/detail/chat prompts inside their endpoints. They are intentionally written in French; preserve the language and section headings (`## 1. Nouveautés majeures`, etc.) since the PDF renderer (`build_pdf_story`) and frontend markdown layout key off `## ` / `- ` / `|` line prefixes.

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
