from sqlalchemy import select

from app.core.security import create_access_token
from app.models.project import Project
from app.models.user import User


async def _get_demo_project_id(session_factory, owner_id: int) -> int:
    async with session_factory() as session:
        project = (
            await session.execute(select(Project).where(Project.owner_id == owner_id))
        ).scalars().one()
        return project.id


async def test_create_template_requires_auth(test_client):
    response = await test_client.post("/prompt-templates", json={"project_id": 1, "name": "T"})
    assert response.status_code == 401


async def test_create_template_rejects_unowned_project(test_client, session_factory, seeded_demo_user):
    async with session_factory() as session:
        other_user = User(email="other-prompt@example.com", hashed_password="x")
        session.add(other_user)
        await session.flush()
        other_project = Project(owner_id=other_user.id, name="Not Yours")
        session.add(other_project)
        await session.flush()
        await session.commit()
        other_project_id = other_project.id

    token = create_access_token(subject=str(seeded_demo_user.id))
    response = await test_client.post(
        "/prompt-templates",
        json={"project_id": other_project_id, "name": "T"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


async def test_create_template_and_version_round_trip(test_client, session_factory, seeded_demo_user):
    project_id = await _get_demo_project_id(session_factory, seeded_demo_user.id)
    token = create_access_token(subject=str(seeded_demo_user.id))
    headers = {"Authorization": f"Bearer {token}"}

    create_response = await test_client.post(
        "/prompt-templates", json={"project_id": project_id, "name": "Support agent"}, headers=headers
    )
    assert create_response.status_code == 201
    template_id = create_response.json()["id"]

    version_response = await test_client.post(
        f"/prompt-templates/{template_id}/versions",
        json={"content": "Answer concisely: {question}"},
        headers=headers,
    )
    assert version_response.status_code == 201
    assert version_response.json()["version_number"] == 1

    list_response = await test_client.get(f"/prompt-templates/{template_id}/versions")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


async def test_create_version_rejects_missing_placeholder(test_client, session_factory, seeded_demo_user):
    project_id = await _get_demo_project_id(session_factory, seeded_demo_user.id)
    token = create_access_token(subject=str(seeded_demo_user.id))
    headers = {"Authorization": f"Bearer {token}"}

    create_response = await test_client.post(
        "/prompt-templates", json={"project_id": project_id, "name": "T"}, headers=headers
    )
    template_id = create_response.json()["id"]

    version_response = await test_client.post(
        f"/prompt-templates/{template_id}/versions",
        json={"content": "No placeholder here."},
        headers=headers,
    )
    assert version_response.status_code == 400


async def test_list_versions_requires_no_auth(test_client, session_factory, seeded_demo_user):
    project_id = await _get_demo_project_id(session_factory, seeded_demo_user.id)
    token = create_access_token(subject=str(seeded_demo_user.id))
    create_response = await test_client.post(
        "/prompt-templates",
        json={"project_id": project_id, "name": "T"},
        headers={"Authorization": f"Bearer {token}"},
    )
    template_id = create_response.json()["id"]

    response = await test_client.get(f"/prompt-templates/{template_id}/versions")
    assert response.status_code == 200


async def test_list_templates_requires_no_auth_and_nests_versions(test_client, session_factory, seeded_demo_user):
    """Phase 8: backs the Prompt Testing dashboard page."""
    project_id = await _get_demo_project_id(session_factory, seeded_demo_user.id)
    token = create_access_token(subject=str(seeded_demo_user.id))
    headers = {"Authorization": f"Bearer {token}"}

    create_response = await test_client.post(
        "/prompt-templates", json={"project_id": project_id, "name": "Support agent"}, headers=headers
    )
    template_id = create_response.json()["id"]
    await test_client.post(
        f"/prompt-templates/{template_id}/versions",
        json={"content": "Answer concisely: {question}"},
        headers=headers,
    )

    response = await test_client.get("/prompt-templates", params={"project_id": project_id})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == template_id
    assert len(body[0]["versions"]) == 1
    assert body[0]["versions"][0]["content"] == "Answer concisely: {question}"


async def test_list_templates_scoped_to_project(test_client, session_factory, seeded_demo_user):
    project_id = await _get_demo_project_id(session_factory, seeded_demo_user.id)
    token = create_access_token(subject=str(seeded_demo_user.id))
    headers = {"Authorization": f"Bearer {token}"}
    await test_client.post("/prompt-templates", json={"project_id": project_id, "name": "T"}, headers=headers)

    async with session_factory() as session:
        other_user = User(email="other-prompt-list@example.com", hashed_password="x")
        session.add(other_user)
        await session.flush()
        other_project = Project(owner_id=other_user.id, name="Other")
        session.add(other_project)
        await session.flush()
        await session.commit()
        other_project_id = other_project.id

    response = await test_client.get("/prompt-templates", params={"project_id": other_project_id})
    assert response.status_code == 200
    assert response.json() == []
