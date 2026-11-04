"""Health endpoint is anonymous: its failure body must not leak internals."""

import pytest

pytestmark = pytest.mark.django_db


def test_healthz_failure_body_is_generic(client, monkeypatch):
    from apps.dashboard import views

    class Boom:
        def __enter__(self):
            raise RuntimeError("password=hunter2 host=db.internal")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(views.connection, "cursor", lambda: Boom())

    resp = client.get("/healthz")

    assert resp.status_code == 503
    assert resp.json() == {"status": "error", "db": "error"}
    assert b"hunter2" not in resp.content
