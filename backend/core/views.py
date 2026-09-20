from django.db import DatabaseError, connection
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response


@api_view(["GET"])
def health(request: Request) -> Response:
    db_ok = False
    pgvector_ok = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            db_ok = True
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            pgvector_ok = cursor.fetchone() is not None
    except DatabaseError:
        pass

    healthy = db_ok and pgvector_ok
    return Response(
        {"status": "ok" if healthy else "error", "db": db_ok, "pgvector": pgvector_ok},
        status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
