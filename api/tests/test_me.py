"""
/me - the signed-in user's own account.

Small surface, but it carries one join that isn't a SQL join: email lives on
auth.users, not profiles, so it reaches the response through the verified token
claims rather than the row.
"""
from conftest import USER_ID, FakeDB

PROFILE = "FROM profiles"


def test_me_requires_authentication(client):
    db = FakeDB()
    assert client(db, authenticated=False).get("/me").status_code == 401


def test_me_returns_the_profile_row(client):
    db = FakeDB(routes=[(PROFILE, [
        {"id": USER_ID, "username": "siddarth_t1", "bars": 10000},
    ])])
    body = client(db).get("/me").json()

    assert body["id"] == USER_ID
    assert body["username"] == "siddarth_t1"
    # Decimal, not float: bars is NUMERIC(12,2) and must not pick up binary
    # rounding error on the way out - this is the number that gets spent.
    assert body["bars"] == "10000"


def test_me_takes_email_from_the_token_not_the_database(client):
    # profiles has no email column, so a row that somehow carried one must not win
    # over the verified claim.
    db = FakeDB(routes=[(PROFILE, [
        {"id": USER_ID, "username": "siddarth_t1", "bars": 10000},
    ])])
    assert client(db).get("/me").json()["email"] == "tester@example.com"


def test_me_looks_up_the_token_subject(client):
    db = FakeDB(routes=[(PROFILE, [
        {"id": USER_ID, "username": "siddarth_t1", "bars": 10000},
    ])])
    client(db).get("/me")

    _, params = db.sql_matching(PROFILE)[0]
    assert params == (USER_ID,)


def test_me_returns_404_when_the_profile_row_is_missing(client):
    # The trigger on auth.users creates this row at signup, so its absence means
    # the account predates the trigger or the row was deleted by hand.
    db = FakeDB(routes=[(PROFILE, [])])
    assert client(db).get("/me").status_code == 404
