"""Task T3 verify: registration route disabled/absent; login issues a valid JWT."""

from app.core.security import decode_access_token


async def test_login_succeeds_with_seeded_demo_user(test_client, seeded_demo_user):
    response = await test_client.post(
        "/auth/login",
        data={"username": seeded_demo_user.email, "password": "test-password"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert decode_access_token(body["access_token"]) == str(seeded_demo_user.id)


async def test_login_rejects_wrong_password(test_client, seeded_demo_user):
    response = await test_client.post(
        "/auth/login",
        data={"username": seeded_demo_user.email, "password": "wrong-password"},
    )
    assert response.status_code == 401


async def test_login_rejects_unknown_email(test_client):
    response = await test_client.post(
        "/auth/login",
        data={"username": "nobody@example.com", "password": "anything"},
    )
    assert response.status_code == 401


async def test_no_public_registration_endpoint(test_client):
    """eng-review D10: no open self-registration on the public deploy."""
    response = await test_client.post(
        "/auth/register", json={"email": "attacker@example.com", "password": "x"}
    )
    assert response.status_code == 404
