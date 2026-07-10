LLM Evaluation Platform

This project is a practical toolkit for evaluating language models. It helps you run repeatable tests, collect DeepEval metrics (faithfulness, bias, toxicity, relevancy), and compare models using blind arena matches and Elo ratings. Think of it as a small lab for model benchmarking and prompt regression testing.

Why this repo exists

- Run real evaluations across providers (OpenAI, Anthropic, Gemini, LLaMA variants, etc.).
- Automate scoring with DeepEval and keep a history of runs for comparisons.
- Let humans and LLMs vote in blind pairwise arena matches and maintain Elo rankings.
- Make it easy to run locally for demos or development.

What’s included (high level)

- Backend (app/): FastAPI service, SQLAlchemy models, services, and route handlers.
- Frontend (frontend/): Next.js app with leaderboards, run controls, and arena UI.
- Workers (app/workers): Celery + Redis workers to run evaluations in parallel.
- Migrations (migrations/): Alembic migration files.
- Monitoring (monitoring/): Prometheus + Grafana provisioning for quick observability.

Quick start (Docker, recommended)

Prereqs: Docker, Docker Compose, Python 3.11, Node.js (18+)

1) Prepare environment

Windows PowerShell example:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env -Force
```

2) Bring up infra

```powershell
docker compose up -d
```

3) Apply migrations

```powershell
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt  # optional
.\.venv\Scripts\python -m alembic upgrade head
```

4) Run the backend and worker

API:

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Worker:

```powershell
.\.venv\Scripts\python -m celery -A app.workers.celery_app worker --pool=solo --loglevel=info
```

5) Start the frontend (separate terminal)

```powershell
Set-Location frontend
npm install
npm run dev
```

Where to look in your browser

- Frontend: http://localhost:3000
- API & docs: http://localhost:8000 (try /docs)
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3001

Native (no Docker) notes

- You can run Postgres and Redis locally and point DATABASE_URL and REDIS_URL in .env to them. For quick testing, a SQLite URL (sqlite+aiosqlite:///./dev.db) works, but avoid it for production.

Seeds & demo account

On first run the app seeds a demo user and sample data. Credentials (change them in app/main.py if you want):

- demo@llm-eval-platform.dev / demo-password-change-me

Common endpoints

- POST /runs — start an evaluation run
- GET /runs/{id} — check status and results
- GET /leaderboard — model rankings
- GET /arena/next-comparison — get a blind comparison to vote on
- POST /arena/vote — submit a vote
- GET /metrics — Prometheus metrics


