from app.models.llm_model import LLMModel
from app.repositories.base import BaseRepository


class LLMModelRepository(BaseRepository[LLMModel]):
    model = LLMModel
