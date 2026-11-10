"""Prepara um banco limpo antes de importar o app.

SQLite (padrão):  pytest
Postgres:         DATABASE_URL=postgresql://... pytest
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if os.environ.get("DATABASE_URL", "").startswith("postgres"):
    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
        c.execute("DROP TABLE IF EXISTS usuarios CASCADE")
else:
    os.environ["SQLITE_PATH"] = os.path.join(tempfile.mkdtemp(), "teste.db")
