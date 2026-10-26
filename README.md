# AI Technical Watch (Veille IA)

A web application that produces a daily technical watch on AI news (OpenAI, Anthropic, Google, Mistral, Microsoft, AWS, NVIDIA, open-source tooling…). An LLM with live web search (Codex CLI by default, or OpenRouter / Gemini) writes a decision-first report; the React interface lets the team read it, summarise it, annotate it, save individual news, query past reports in a chat, produce a CODIR note, and export to PDF, Word or an email-ready HTML newsletter.

**Full documentation (French): [docs/](docs/README.md)** — [architecture](docs/ARCHITECTURE.md), [API](docs/API.md), [configuration](docs/CONFIGURATION.md), [functional guide](docs/FONCTIONNEL.md), [operations](docs/EXPLOITATION.md).

## Prerequisites

- Python 3.11 (`.python-version`; 3.12/3.13 also work)
- Node.js 18+
- An LLM provider: Codex CLI (`npm install -g @openai/codex`, then `codex login`) — or an OpenRouter API key

## Quick start

```bash
./dev.sh
```

`dev.sh` creates `backend/.env` from `.env.example` if needed, builds `backend/venv` with Python 3.11, installs the dependencies, and starts the backend (http://localhost:8000) and the frontend (http://localhost:5173). Open the frontend and click **« Lancer la veille »**.

Configuration lives in `backend/.env`; every variable is described in [docs/CONFIGURATION.md](docs/CONFIGURATION.md). The main one is `LLM_PROVIDER` (`codex` by default; `openrouter` needs `OPENROUTER_API_KEY` and has no web search unless `OPENROUTER_WEB_SEARCH=true`).

Manual start, containers (`./compose.sh start`), tests and troubleshooting: [docs/EXPLOITATION.md](docs/EXPLOITATION.md).

## Reddit community signals (optional)

With `REDDIT_ENABLED=true`, the daily watch also reads the top posts of the last 24 h from `REDDIT_SUBREDDITS` (default `LocalLLaMA,ClaudeAI,OpenAI,ChatGPTCoding,MachineLearning,singularity`) through Reddit's public RSS feed — no Reddit account or app (Reddit grants none, and its JSON API returns 403 without one). All subreddits are read in a single request, since Reddit allows about one anonymous request per minute. The feed has no score, so the rank in the day's top is used instead; meme-like posts and duplicate links are dropped, and at most `REDDIT_MAX_POSTS_PER_SUB` (5) per subreddit and `REDDIT_MAX_POSTS` (15) in total are added to the prompt as leads to verify on primary sources. `REDDIT_USER_AGENT` and `REDDIT_TIMEOUT_SECONDS` are optional. If Reddit fails, the watch is generated exactly as without it. Check what would be sent with `GET /reddit/preview?subreddit=LocalLLaMA&period=day` (no LLM call). Details: [docs/CONFIGURATION.md](docs/CONFIGURATION.md#reddit).

## Daily run (cron) and newsletter

`POST /cron/daily` generates today's watch if it does not exist yet (`?force=true` to regenerate) and returns the report id and its newsletter URL. Generation takes several minutes, so give the HTTP client a long timeout:

```bash
# crontab -e : every weekday at 7:30
30 7 * * 1-5 curl -fsS -X POST --max-time 900 -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/cron/daily >> ~/veille-cron.log 2>&1
```

`GET /reports/{id}/newsletter` returns the email-ready HTML body (Gmail/Outlook safe). The « Newsletter » button in the report view opens it in a new tab.

## Sending the newsletter by email

Configure SMTP in `backend/.env` (template: `.env.example` at the repo root, which `dev.sh` / `compose.sh` copy to `backend/.env`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `SMTP_HOST` | — | SMTP server (required) |
| `SMTP_PORT` | `587` | `465` switches to implicit SSL |
| `SMTP_USER` / `SMTP_PASSWORD` | — | Credentials (empty user = unauthenticated relay); the password is never returned by the API nor logged |
| `SMTP_STARTTLS` | `true` | STARTTLS before login |
| `SMTP_SSL` | `true` if port 465 | Implicit SSL |
| `SMTP_TIMEOUT_SECONDS` | `30` | SMTP timeout |
| `MAIL_FROM` | `SMTP_USER` | Sender, e.g. `Veille IA <veille@april.fr>` |
| `MAIL_TO` | — | Comma-separated recipients (required) |
| `MAIL_AUTO_SEND` | `false` | `true`: `/cron/daily` emails the day's newsletter once |

Then « Envoyer par mail » in the report view (or `POST /reports/{id}/send`) sends it with the subject « Veille IA – <date> ». `GET /mail/info` shows whether mail is configured. Without SMTP settings the app runs normally; sending returns 503. Details: [docs/CONFIGURATION.md](docs/CONFIGURATION.md#mail-smtp).

## Tech stack

- **Frontend:** React 19, TypeScript, Vite, React-Markdown + remark-gfm, Lucide icons, APRIL design tokens (Poppins).
- **Backend:** FastAPI, SQLAlchemy, SQLite, Codex CLI / OpenRouter / Gemini, ReportLab (PDF), python-docx (Word).
