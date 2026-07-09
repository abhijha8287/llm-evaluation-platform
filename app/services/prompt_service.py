from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompt import PromptTemplate, PromptVersion
from app.models.question import Question
from app.repositories.prompt_repository import PromptTemplateRepository, PromptVersionRepository

# Every PromptVersion.content must contain this placeholder — the regression
# engine renders it with str.format(question=...) before sending it to a
# model. Validated at creation time (not render time) so a broken template
# is caught immediately, not discovered mid-regression-run after real API
# calls have already been made against the other questions.
REQUIRED_PLACEHOLDER = "{question}"


class PromptTemplateContentError(ValueError):
    pass


class PromptService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_template(self, project_id: int, name: str) -> PromptTemplate:
        return await PromptTemplateRepository(self.session).add(
            PromptTemplate(project_id=project_id, name=name)
        )

    async def create_version(self, prompt_template_id: int, content: str) -> PromptVersion:
        if REQUIRED_PLACEHOLDER not in content:
            raise PromptTemplateContentError(
                f"Prompt template content must contain the {REQUIRED_PLACEHOLDER} placeholder"
            )
        version_repo = PromptVersionRepository(self.session)
        next_number = await version_repo.next_version_number(prompt_template_id)
        return await version_repo.add(
            PromptVersion(
                prompt_template_id=prompt_template_id, version_number=next_number, content=content
            )
        )


def render_prompt(prompt_version: PromptVersion, question: Question) -> str:
    """Pure function, no I/O — kept separate from PromptService so
    regression_service/eval_tasks can call it without needing a session."""
    return prompt_version.content.format(question=question.text)
