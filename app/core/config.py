from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/llm_eval"

    # Auth (D10: login-only, single seeded demo user, no open registration)
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24

    # Redis (Celery broker + leaderboard cache, D13)
    redis_url: str = "redis://localhost:6379/0"

    # D2: rate limit on trigger-run endpoint, independent of auth state
    max_runs_per_day: int = 3

    # D9: fixed, separate judge model for all LLM-as-judge metrics — avoids
    # self-preference bias when the same family being judged also judges.
    judge_model: str = "gpt-4o-mini"

    # Provider API keys (never accepted from request bodies — server-side only)
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    together_api_key: str = ""
    deepseek_api_key: str = ""

    # D5: sampling cap per Constraints — 20-30 questions/dataset/run, not the
    # full dataset every time.
    default_sample_size: int = 25


@lru_cache
def get_settings() -> Settings:
    return Settings()
