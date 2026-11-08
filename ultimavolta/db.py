"""Camada de banco: SQLite local / Postgres (Supabase) em produção.

Escolha pela variável DATABASE_URL:
  - ausente           -> SQLite em ./ultimavolta.db
  - postgresql://...  -> Postgres
O SQL do app é escrito com '?' como marcador; aqui é traduzido para '%s' no Postgres.
"""
import os
import sqlite3

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))
SQLITE_PATH = os.environ.get("SQLITE_PATH", os.path.join(os.path.dirname(__file__), "ultimavolta.db"))

if IS_PG:
    import psycopg
    from psycopg.rows import dict_row


def _sql(query):
    return query.replace("?", "%s") if IS_PG else query


def connect():
    if IS_PG:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def query_one(query, params=()):
    with connect() as conn:
        cur = conn.execute(_sql(query), params)
        row = cur.fetchone()
        return dict(row) if row else None


def query_all(query, params=()):
    with connect() as conn:
        cur = conn.execute(_sql(query), params)
        return [dict(r) for r in cur.fetchall()]


def execute(query, params=()):
    with connect() as conn:
        conn.execute(_sql(query), params)
        conn.commit()


SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    senha_hash TEXT NOT NULL,
    perfil TEXT NOT NULL CHECK (perfil IN ('instrutor', 'aluno')),
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    senha_hash TEXT NOT NULL,
    perfil TEXT NOT NULL CHECK (perfil IN ('instrutor', 'aluno')),
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def init_db():
    with connect() as conn:
        if IS_PG:
            conn.execute(SCHEMA_PG)
        else:
            conn.executescript(SCHEMA_SQLITE)
        conn.commit()
