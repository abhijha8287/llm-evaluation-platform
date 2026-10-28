# LLM Evaluation Platform

A toolkit for comparing language models across providers: automated DeepEval scoring, prompt regression tests and a blind pairwise arena with Elo rankings.

## Why this exists
To run repeatable, comparable evaluations of LLMs instead of judging outputs by eye, and to keep a history of results so model or prompt changes can be checked against earlier runs.

## What it does
- Runs evaluation jobs against OpenAI, Anthropic, Gemini, Groq, Together and DeepSeek models through LiteLLM
- Scores outputs with DeepEval metrics (faithfulness, relevancy, bias, toxicity) using a judge model
- Runs prompt regression tests to catch quality drops
- Blind pairwise arena: people or an LLM judge vote, and models get Elo ratings
- Processes runs in parallel with Celery workers
- Exposes Prometheus metrics with ready-made Grafana dashboards
- Next.js frontend with leaderboard, run controls and arena

## Project structure
```
llm-evaluation-platform/
├── app/
│   ├── api/            FastAPI route handlers
│   ├── core/           Settings, auth, database, seed data
│   ├── evaluation/     DeepEval scoring
│   ├── llm/            LiteLLM provider calls
│   ├── models/         SQLAlchemy tables
│   ├── repositories/   Database access layer
│   ├── services/       Runs, arena, Elo, regression, cost
│   ├── workers/        Celery evaluation tasks
│   ├── monitoring/     Prometheus metrics
│   └── main.py         FastAPI entry point
├── frontend/           Next.js dashboard
├── migrations/         Alembic migrations
├── monitoring/         Prometheus and Grafana config
├── tests/              pytest suite
├── docker-compose.yml  Postgres, Redis, API, worker, frontend, monitoring
├── design-llm-evaluation-platform.md   Design document
└── pyproject.toml      Python project and dependencies
```

## Getting started
Requirements: Docker and Docker Compose, Python 3.11+, Node.js 18+, at least one LLM provider key.
```bash
git clone https://github.com/abhijha8287/llm-evaluation-platform.git
cd llm-evaluation-platform
cp .env.example .env                    # add provider keys
docker compose up -d                    # Postgres, Redis, Prometheus, Grafana
python -m venv .venv && source .venv/bin/activate
pip install -e .
alembic upgrade head
uvicorn app.main:app --reload --port 8000
celery -A app.workers.celery_app worker --pool=solo --loglevel=info   # second terminal
cd frontend && npm install && npm run dev                              # third terminal
```
| Service | Address |
|:--|:--|
| Frontend | http://localhost:3000 |
| API and docs | http://localhost:8000/docs |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3001 |

A demo user and sample data are created on first run (see `app/main.py`).

## Configuration
| Variable | Purpose |
|:--|:--|
| `DATABASE_URL` | Postgres URL (SQLite works for quick tests) |
| `REDIS_URL` | Redis for Celery |
| `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES` | API authentication |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `TOGETHER_API_KEY`, `DEEPSEEK_API_KEY` | Provider keys (set the ones you use) |
| `JUDGE_MODEL` | Model that scores outputs |
| `MAX_RUNS_PER_DAY`, `DEFAULT_SAMPLE_SIZE` | Usage limits and defaults |
| `CELERY_METRICS_PORT` | Worker metrics port |

## Main endpoints
| Method | Path | Purpose |
|:--|:--|:--|
| POST | `/runs` | Start an evaluation run |
| GET | `/runs/{id}` | Run status and results |
| GET | `/leaderboard` | Model rankings |
| GET | `/arena/next-comparison` | Next blind comparison |
| POST | `/arena/vote` | Submit a vote |
| GET | `/metrics` | Prometheus metrics |

## Tests
```bash
pytest
```

## Tech stack
Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Redis, Celery, LiteLLM, DeepEval, Prometheus, Grafana, Next.js, Docker
