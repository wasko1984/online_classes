import os
from pathlib import Path

import pytest

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "Admin@1984")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")

    import importlib
    import app as app_module
    importlib.reload(app_module)

    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as client:
        yield client, app_module

def token(client):
    with client.session_transaction() as sess:
        return sess["_csrf_token"]

def test_home_and_health(client):
    c, _ = client
    assert c.get("/").status_code == 200
    assert c.get("/health").status_code == 200

def test_csrf_blocks_registration(client):
    c, _ = client
    response = c.post("/register", data={"full_name": "A"})
    assert response.status_code == 400

def test_registration_flow(client):
    c, mod = client
    response = c.post(
        "/register",
        data={
            "_csrf_token": token(c),
            "full_name": "Ahmad Test",
            "email": "ahmad@example.com",
            "phone": "+2348000000000",
            "course": "Cybersecurity",
            "passport": (Path(__file__).parent / "fixtures" / "passport.jpg").open("rb"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    student = mod.db.session.scalar(mod.db.select(mod.Student))
    assert student is not None
    assert student.status == "pending"
    assert student.reg_code.startswith("WV")
