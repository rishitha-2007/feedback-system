import mongomock, pytest
from app import create_app

@pytest.fixture
def client():
    app = create_app(mongomock.MongoClient().db); app.config["TESTING"] = True
    return app.test_client()

def login(c, u="24CSE101", p="student123", path="/login"):
    return c.post(path, data={"username": u, "password": p}, follow_redirects=True)

GOOD = {"course": "Operating Systems|Faculty B", "teaching_quality": 5, "communication": 4, "doubt_clarification": 4, "comments": "ok"}

def test_student_login_ok_and_bad(client):
    assert b"Faculty feedback" in login(client).data
    assert b"Wrong ID" in login(client, p="nope").data

def test_submit_feedback(client):
    login(client)
    assert b"submitted successfully" in client.post("/feedback", data=GOOD, follow_redirects=True).data

def test_invalid_rating(client):
    login(client)
    assert client.post("/feedback", data={**GOOD, "communication": 9}).status_code == 400

def test_duplicate_blocked(client):
    login(client); client.post("/feedback", data=GOOD)
    assert client.post("/feedback", data=GOOD).status_code == 409

def test_admin_routes_protected(client):
    assert client.get("/admin").status_code == 302
    login(client)
    assert client.get("/admin").status_code == 302  # student cannot see admin

def test_admin_dashboard_and_filter(client):
    login(client); client.post("/feedback", data=GOOD); client.get("/logout")
    login(client, "admin", "admin123", "/admin/login")
    assert b"Total submissions" in client.get("/admin").data
    r = client.get("/admin/responses?subject=Operating Systems")
    assert b"Faculty B" in r.data and b"24CSE101" not in r.data  # anonymous
    assert client.get("/admin/export.csv").mimetype == "text/csv"
