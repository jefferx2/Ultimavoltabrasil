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
-- O app acessa direto pelo Postgres; a API pública do Supabase fica bloqueada.
ALTER TABLE usuarios ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    REVOKE ALL ON usuarios FROM anon, authenticated;
  END IF;
END $$;
"""


# Colunas acrescentadas depois da criação da tabela (aplicadas em bancos já existentes).
# nome -> tipo (o mesmo nos dois bancos)
COLUNAS_USUARIOS = {
    "instrutor_id": "INTEGER REFERENCES usuarios(id)",
    "data_nascimento": "TEXT",
    "prova_principal": "TEXT",
    "telefone": "TEXT",
    "observacoes": "TEXT",
    "trocar_senha": "INTEGER NOT NULL DEFAULT 0",
}


def _colunas_existentes(conn, tabela):
    if IS_PG:
        cur = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s", (tabela,))
        return {r["column_name"] for r in cur.fetchall()}
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({tabela})").fetchall()}


def init_db():
    with connect() as conn:
        if IS_PG:
            conn.execute(SCHEMA_PG)
        else:
            conn.executescript(SCHEMA_SQLITE)
        existentes = _colunas_existentes(conn, "usuarios")
        for nome, tipo in COLUNAS_USUARIOS.items():
            if nome not in existentes:
                # IF NOT EXISTS: os workers do gunicorn sobem juntos e podem tentar ao mesmo tempo
                se_nao = "IF NOT EXISTS " if IS_PG else ""
                conn.execute(f"ALTER TABLE usuarios ADD COLUMN {se_nao}{nome} {tipo}")
        conn.commit()
