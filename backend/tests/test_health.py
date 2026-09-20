from unittest import mock

import pytest
from django.db import OperationalError, connection
from django.test import Client


@pytest.mark.django_db
def test_health_ok(client: Client) -> None:
    response = client.get("/api/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": True, "pgvector": True}


def test_health_reports_unreachable_db(client: Client) -> None:
    with mock.patch("core.views.connection") as fake_connection:
        fake_connection.cursor.side_effect = OperationalError("connection refused")
        response = client.get("/api/health/")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": False, "pgvector": False}


@pytest.mark.django_db
def test_health_reports_missing_pgvector(client: Client) -> None:
    with connection.cursor() as cursor:
        cursor.execute("DROP EXTENSION vector CASCADE")

    response = client.get("/api/health/")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": True, "pgvector": False}


@pytest.mark.django_db
def test_migrations_enable_pgvector() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        assert cursor.fetchone() is not None
