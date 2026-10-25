# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Full human documentation (French) lives in [docs/](docs/README.md): architecture, API (all endpoints), configuration (all env vars), functional guide, operations. Keep it in sync when you change endpoints, env vars, prompts or report structure.

## Project

AI Technical Watch ("Veille IA"): FastAPI backend + React/Vite frontend that triggers LLM-generated (Codex by default) technical-watch reports, stores them in SQLite, and exposes summaries, per-extract detail/definition, notes, saved news, chat-over-reports (optional web search), CODIR notes, PDF/DOCX export and an email-ready HTML newsletter.

## Commands

Local dev (one shot, both stacks): `./dev.sh` from repo root. Creates `backend/venv` with Python 3.11 (recreated if built with another version), installs deps, runs `uvicorn app.main:app --reload --port 8000` and `npm run dev` (Vite on 5173).

Backend only — from `backend/`:
- Run: `source venv/bin/activate && uvicorn app.main:app --reload`
- Install deps: `pip install -r requirements.txt`
- Tests: from repo root, `pytest test_llm_providers.py test_news_items.py test_prompts_renderer.py test_chat_and_watch.py test_newsletter.py test_reddit.py` (`conftest.py` isolates the DB in `test_app.db` and forces `REDDIT_ENABLED=false`; LLM calls are monkeypatched, Reddit goes through `httpx.MockTransport` — tests must never hit the network). A bare `pytest` fails at collection because `test_gemini_auth.py` is a manual script importing `google.genai` (not in requirements) — list files or `--ignore=test_gemini_auth.py`. No suite under `backend/`.

Frontend only — from `frontend/`:
- Dev: `npm run dev`
- Build (typecheck + bundle): `npm run build` — runs `tsc -b` then `vite build`. Use this to typecheck.
- Lint: `npm run lint`

Containers: `./compose.sh start` (bootstraps `backend/.env` and `API_TOKEN`) or `podman-compose up --build` (also works with `docker compose`). Mounts `./data` for the SQLite DB, `./backend/app` (code only — the container runs uvicorn without `--reload`, restart after edits) and `~/.codex`.

## Architecture

**Backend (`backend/app/`)** — single-file FastAPI app:
- `main.py` holds the 23 endpoints, LLM provider dispatch, prompt strings, news extraction, and PDF/DOCX rendering. Most logic lives here; do not split prematurely. Two exceptions with no app dependency: `newsletter.py` (pure renderer) and `reddit.py` (Reddit reader).
- `models.py` / `schemas.py` / `database.py` are SQLAlchemy ORM, Pydantic, and engine setup. SQLite at `backend/sql_app.db` (or `DATABASE_URL` env, e.g. `./data/sql_app.db` in container).
- Schema is created via `models.Base.metadata.create_all` on import. Lightweight in-place migrations live in `ensure_reports_schema()` and `ensure_news_items_schema()` (called at import), followed by `backfill_news_items()`. Add new column migrations there rather than introducing Alembic unless the user asks.
- Tables: `reports` (typed via `report_type`, default `technical_watch`), `report_summaries` (1:1 with report), `notes` (highlights/annotations), `chat_messages` (history with serialized `report_ids` JSON column), `news_items` (one row per « Nouveautés détaillées » entry; saved items survive report deletion with `report_id` set to NULL).

**LLM providers** — selected by `LLM_PROVIDER` env (`codex` default, `openrouter`, `gemini`). `generate_llm_content(prompt, timeout_seconds, web_search=False)` is the single dispatch point — call it (preceded by `ensure_llm_ready()`) instead of touching a backend directly.
1. `codex` (default): shells out to `codex exec --skip-git-repo-check --ephemeral --sandbox read-only -o <tmpfile> -c web_search="live"|"disabled" -`, prompt on stdin (reports exceed the per-argument size limit), answer read from the `-o` file. Auth comes from `codex login` (`~/.codex`). Optional `CODEX_MODEL`, `CODEX_REASONING_EFFORT`, `CODEX_BIN`, `CODEX_WEB_SEARCH` (default true). Web search is requested only by watch generation (`/reports/trigger`, `/cron/daily`) and by chat when the user ticks « Chercher aussi sur le web ».
2. `openrouter`: OpenAI-compatible `POST /api/v1/chat/completions` via httpx with `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` (default `openrouter/auto`). No internet access unless `OPENROUTER_WEB_SEARCH=true` (paid `web` plugin) — without it the daily watch relies on model knowledge only.
3. `gemini` (legacy): CLI backend (`gemini --output-format json`, when `~/.gemini/oauth_creds.json` and `gemini` on PATH exist; model mapped through `CLI_MODEL_ALIASES`) or `google.generativeai` SDK via OAuth creds / `GEMINI_API_KEY`. In containers the OAuth refresh needs `GEMINI_OAUTH_CLIENT_ID` / `GEMINI_OAUTH_CLIENT_SECRET`. Google SDK modules (`google.generativeai`, `google.auth`, `google.oauth2`) are imported lazily (`import_genai()` and local imports) so they never load with Codex/OpenRouter — keep them out of module-level imports.

Timeouts: `LLM_TIMEOUT_SECONDS` (default 90) and `LLM_REPORT_TIMEOUT_SECONDS` (default 600, used for the watch and CODIR note). The backend Dockerfile installs `@openai/codex`; `podman-compose.yml` mounts `${HOME}/.codex` read-write so token refresh works.

**Auth on the API** — `verify_token` is a `Security(HTTPBearer)` dep applied to every endpoint. It is a no-op when `API_TOKEN` env is unset (dev default). When set, every request needs `Authorization: Bearer <API_TOKEN>`. `frontend/src/api.ts` sends it on every axios call when `VITE_API_TOKEN` is set (`dev.sh` and `compose.sh` derive it from `backend/.env`); both values must match.

**CORS** — driven by `ALLOWED_ORIGINS` env (comma-separated, default `http://localhost:5173`). `allow_credentials=False`, so don't switch the frontend to cookie auth without flipping that.

**Prompts** — `TECHNICAL_PROMPT` (large French prompt for daily watch generation; always sent through `build_technical_prompt(db)`, which prepends today's date and the covered 24h window in Europe/Paris and appends the titles of recent `news_items` as « Déjà couvert » to avoid repeats). Chat uses `build_chat_prompt()` with full report content + summary + notes (`build_report_chat_context`), the last 6 conversation messages sent by the frontend, and an optional `web_search` flag (rejected with 400 when the provider has no web access; see `GET /llm/info`). `persist=false` keeps technical calls (dashboard project synthesis) out of chat history. Summary/detail/definition prompts stay inline in their endpoints. They are intentionally written in French; preserve the language and the report section headings (`## TL;DR`, `## Radar décisionnel` with `### À tester maintenant` / `### À surveiller` / `### À ignorer`, `## Nouveautés détaillées` with one `### title` per item and labelled bullets such as `- **Maturité** : …`, `## Sécurité & gouvernance`, `## Signaux faibles & recherche`, `## Note de méthode`) — `test_prompts_renderer.py` asserts them, and news extraction, the frontend structured view, the newsletter and the PDF renderer key off `## ` / `### ` / `- ` / `|` line prefixes. Older reports use the legacy `## 1. Nouveautés majeures` layout and fall back to plain markdown in the UI.

**Reddit signals** — `backend/app/reddit.py`, off unless `REDDIT_ENABLED=true`. `build_technical_prompt(db, now=None, reddit_posts=None)` calls `reddit_posts_for_watch()` when `reddit_posts` is None and appends `build_reddit_prompt_section()` (« # Signaux communautaires Reddit »: title, subreddit, score, comments, thread link, shared link; instruction to verify on a primary source and not create a Reddit section). `fetch_subreddit_posts(sub, period)` hits `/r/<sub>/top` with a dedicated User-Agent and `REDDIT_TIMEOUT_SECONDS` (10): app-only OAuth (`REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` → `client_credentials` token cached, `oauth.reddit.com`) or the public `top.json` fallback. `filter_posts()` applies the period window (24h for `day`), `REDDIT_MIN_SCORE` (50), drops stickied/NSFW/meme flairs, dedups by canonical external URL across subreddits, caps at `REDDIT_MAX_POSTS` (15). Subreddits from `REDDIT_SUBREDDITS` (default LocalLLaMA, ClaudeAI, OpenAI, ChatGPTCoding, MachineLearning, singularity); `REDDIT_USER_AGENT` optional. Every Reddit error (HTTP, 429, timeout, bad JSON) is logged and yields `[]` — Reddit must never fail the watch, and the report gains no `##` section (Reddit threads only as a bullet in « Signaux faibles & recherche »). `GET /reddit/preview?subreddit=&period=` returns the filtered posts plus `errors`, no LLM call, works even when disabled. The public JSON is usually 403 from servers/containers: OAuth is the realistic setup.

**Daily run & newsletter** — `POST /cron/daily` (for an external cron; `?force=true` regenerates) creates today's watch (Europe/Paris date) only if none exists, and returns `newsletter_url`. `/reports/trigger` and the cron share `generate_watch_report()` and `WATCH_GENERATION_LOCK` (409 when a run is in progress); both are sync `def` so the multi-minute LLM call runs in FastAPI's threadpool instead of blocking the event loop — keep LLM-calling endpoints sync. `GET /reports/{id}/newsletter` renders the report deterministically (no LLM) through `backend/app/newsletter.py` into a mail-safe HTML body: starts with `<table>`, tables only, inline styles, `bgcolor` + `background-color` pairs, 4px bar cells instead of `border-left`, ASCII-only via HTML entities, 720px, Cowork colour code (header `#0f2740`, summary `#eef4f9`, rules `#2f8fd6`, security `#fdf5f4`/`#c0392b`, per-actor bar colours in `ACTORS`). `test_newsletter.py` guards these constraints. Nothing is emailed yet.

**PDF export** — pure ReportLab via `build_pdf_story()`. It hand-parses the markdown subset the prompt produces (`##`, `###`, single-level `- ` bullets, `|` tables, standalone images, inline bold and links). Keep generated content within that subset; do not introduce nested lists, `####`, or fenced code blocks without extending `append_markdown_pdf_elements()`. DOCX export (`build_codir_docx`, python-docx) exists only for `codir_note` reports.

**Frontend (`frontend/src/`)**:
- `App.tsx` is the single-page UI (~2,000 lines) — views Tableau de bord, Rapports (structured reading, summary, TOC, selection toolbar), News sauvegardées, Notes, Recherches (chat). Edit in place rather than splitting into many small components unless the user asks.
- `api.ts` reads `API_URL` from `VITE_API_URL` (default `http://localhost:8000`) and adds the Bearer header from `VITE_API_TOKEN`.
- React 19 + Vite 8 + react-markdown + remark-gfm. APRIL design tokens (blue `#004161`, green `#639e30`, orange `#f7aa36`, Poppins) in `index.css`, component styles in `App.css`; the earlier dark-tech theme (`docs/superpowers/specs/2026-04-01-dark-tech-redesign-design.md`) has been replaced.

## Conventions

- All user-facing copy and prompt content is French. Match the surrounding language when editing prompts or UI strings.
- Backend endpoints follow REST under resource paths (`/reports`, `/reports/{id}/summary|detail|definition|notes|news|codir|pdf|docx|newsletter`, `/reports/trigger`, `/cron/daily`, `/news`, `/notes`, `/chat`, `/chat/messages`, `/llm/info`, `/reddit/preview`; full list in `docs/API.md`). New endpoints should accept `_=Depends(verify_token)` to stay protected when `API_TOKEN` is set.
- When adding a column, also extend `ensure_reports_schema()` (or write a sibling helper) so existing dev DBs migrate on next boot.
- `sql_app.db` (and `test_app.db`) are git-ignored local state; treat them as throwaway, not fixtures.
