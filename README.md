# AI Technical Watch (Veille IA)

A web application that automatically monitors AI news from major industry players (OpenAI, Anthropic, Google, etc.), analyzes them with a technical focus using Gemini, and provides a blog-like interface with PDF export.

## Prerequisites
- Node.js (v18+)
- Python (3.9+)
- Gemini API Key

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
   - Edit `.env` and add your `GEMINI_API_KEY`.
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
- **Backend:** FastAPI, SQLAlchemy, SQLite, Google Generative AI (Gemini), xhtml2pdf.
