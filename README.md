# AI Technical Watch (Veille IA)

A web application that automatically monitors AI news from major industry players (OpenAI, Anthropic, Google, etc.), analyzes them with a technical focus using an LLM (Codex CLI by default, or OpenRouter / Gemini), and provides a blog-like interface with PDF export.

## Prerequisites
- Node.js (v18+)
- Python (3.9+)
- Codex CLI (`npm install -g @openai/codex`, then `codex login`) — or an OpenRouter API key

## Setup

### 1. Backend Setup
1. Navigate to the backend directory:
   ```bash
   cd backend
   ```
2. Create a virtual environment and activate it:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Configure environment variables:
   - Create a `.env` file from `.env.example`:
     ```bash
     cp ../.env.example .env
     ```
   - Edit `.env` and choose `LLM_PROVIDER` (`codex` by default; `openrouter` needs `OPENROUTER_API_KEY` and has no web search unless `OPENROUTER_WEB_SEARCH=true`).
5. Start the FastAPI server:
   ```bash
   uvicorn app.main:app --reload
   ```

### 2. Frontend Setup
1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Start the development server:
   ```bash
   npm run dev
   ```

## Usage
- Open your browser at `http://localhost:5173`.
- Click **"Trigger Daily Watch"** to initiate a new technical analysis.
- View historical reports in the sidebar.
- Use **"Export PDF"** to download a clean, technical report for sharing.

## Tech Stack
- **Frontend:** React, TypeScript, Vite, Vanilla CSS, React-Markdown, Lucide Icons.
- **Backend:** FastAPI, SQLAlchemy, SQLite, Codex CLI / OpenRouter / Gemini, ReportLab.
