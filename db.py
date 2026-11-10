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


class Transacao:
    """Várias operações numa única transação (tudo ou nada).

    with db.Transacao() as t:
        novo_id = t.insert("INSERT INTO ... VALUES (?, ?)", (a, b))
        t.execute("UPDATE ...", (...))
    """

    def __enter__(self):
        self.conn = connect()
        return self

    def __exit__(self, exc_type, *_):
        try:
            if exc_type:
                self.conn.rollback()
            else:
                self.conn.commit()
        finally:
            self.conn.close()

    def execute(self, query, params=()):
        self.conn.execute(_sql(query), params)

    def query_all(self, query, params=()):
        return [dict(r) for r in self.conn.execute(_sql(query), params).fetchall()]

    def insert(self, query, params=()):
        if IS_PG:
            return self.conn.execute(_sql(query) + " RETURNING id", params).fetchone()["id"]
        return self.conn.execute(query, params).lastrowid


def insert(query, params=()):
    """INSERT que devolve o id criado."""
    with Transacao() as t:
        return t.insert(query, params)


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
""" + """
CREATE TABLE IF NOT EXISTS macrociclos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aluno_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    nome TEXT NOT NULL,
    competicao TEXT,
    data_inicio TEXT NOT NULL,
    data_competicao TEXT,
    observacoes TEXT,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS fases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    macrociclo_id INTEGER NOT NULL REFERENCES macrociclos(id) ON DELETE CASCADE,
    modalidade TEXT NOT NULL CHECK (modalidade IN ('academia', 'corrida')),
    ordem INTEGER NOT NULL,
    nome TEXT NOT NULL,
    objetivo TEXT,
    semanas INTEGER NOT NULL CHECK (semanas BETWEEN 1 AND 104),
    series TEXT,
    repeticoes TEXT,
    intensidade INTEGER NOT NULL CHECK (intensidade BETWEEN 1 AND 5),
    volume INTEGER NOT NULL CHECK (volume BETWEEN 1 AND 5),
    intensidade_ref TEXT,
    volume_ref TEXT,
    conteudo TEXT
);
CREATE INDEX IF NOT EXISTS ix_macro_aluno ON macrociclos(aluno_id);
CREATE INDEX IF NOT EXISTS ix_fases_macro ON fases(macrociclo_id, modalidade, ordem);
CREATE TABLE IF NOT EXISTS treinos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    macrociclo_id INTEGER NOT NULL REFERENCES macrociclos(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    modalidade TEXT NOT NULL CHECK (modalidade IN ('academia', 'corrida')),
    titulo TEXT,
    observacoes TEXT,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS treino_academia (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    treino_id INTEGER NOT NULL REFERENCES treinos(id) ON DELETE CASCADE,
    ordem INTEGER NOT NULL,
    exercicio TEXT NOT NULL,
    series INTEGER NOT NULL CHECK (series BETWEEN 1 AND 20),
    repeticoes TEXT,
    carga TEXT,
    descanso TEXT,
    observacao TEXT
);
CREATE TABLE IF NOT EXISTS treino_corrida (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    treino_id INTEGER NOT NULL REFERENCES treinos(id) ON DELETE CASCADE,
    ordem INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    repeticoes INTEGER NOT NULL DEFAULT 1 CHECK (repeticoes BETWEEN 1 AND 100),
    distancia_m INTEGER CHECK (distancia_m IS NULL OR distancia_m BETWEEN 1 AND 100000),
    duracao TEXT,
    pace TEXT,
    recuperacao TEXT,
    observacao TEXT
);
CREATE INDEX IF NOT EXISTS ix_treinos_macro ON treinos(macrociclo_id, data);
CREATE INDEX IF NOT EXISTS ix_tacad_treino ON treino_academia(treino_id, ordem);
CREATE INDEX IF NOT EXISTS ix_tcorr_treino ON treino_corrida(treino_id, ordem);
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
CREATE TABLE IF NOT EXISTS macrociclos (
    id SERIAL PRIMARY KEY,
    aluno_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    nome TEXT NOT NULL,
    competicao TEXT,
    data_inicio TEXT NOT NULL,
    data_competicao TEXT,
    observacoes TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS fases (
    id SERIAL PRIMARY KEY,
    macrociclo_id INTEGER NOT NULL REFERENCES macrociclos(id) ON DELETE CASCADE,
    modalidade TEXT NOT NULL CHECK (modalidade IN ('academia', 'corrida')),
    ordem INTEGER NOT NULL,
    nome TEXT NOT NULL,
    objetivo TEXT,
    semanas INTEGER NOT NULL CHECK (semanas BETWEEN 1 AND 104),
    series TEXT,
    repeticoes TEXT,
    intensidade INTEGER NOT NULL CHECK (intensidade BETWEEN 1 AND 5),
    volume INTEGER NOT NULL CHECK (volume BETWEEN 1 AND 5),
    intensidade_ref TEXT,
    volume_ref TEXT,
    conteudo TEXT
);
CREATE INDEX IF NOT EXISTS ix_macro_aluno ON macrociclos(aluno_id);
CREATE INDEX IF NOT EXISTS ix_fases_macro ON fases(macrociclo_id, modalidade, ordem);
CREATE TABLE IF NOT EXISTS treinos (
    id SERIAL PRIMARY KEY,
    macrociclo_id INTEGER NOT NULL REFERENCES macrociclos(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    modalidade TEXT NOT NULL CHECK (modalidade IN ('academia', 'corrida')),
    titulo TEXT,
    observacoes TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS treino_academia (
    id SERIAL PRIMARY KEY,
    treino_id INTEGER NOT NULL REFERENCES treinos(id) ON DELETE CASCADE,
    ordem INTEGER NOT NULL,
    exercicio TEXT NOT NULL,
    series INTEGER NOT NULL CHECK (series BETWEEN 1 AND 20),
    repeticoes TEXT,
    carga TEXT,
    descanso TEXT,
    observacao TEXT
);
CREATE TABLE IF NOT EXISTS treino_corrida (
    id SERIAL PRIMARY KEY,
    treino_id INTEGER NOT NULL REFERENCES treinos(id) ON DELETE CASCADE,
    ordem INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    repeticoes INTEGER NOT NULL DEFAULT 1 CHECK (repeticoes BETWEEN 1 AND 100),
    distancia_m INTEGER CHECK (distancia_m IS NULL OR distancia_m BETWEEN 1 AND 100000),
    duracao TEXT,
    pace TEXT,
    recuperacao TEXT,
    observacao TEXT
);
CREATE INDEX IF NOT EXISTS ix_treinos_macro ON treinos(macrociclo_id, data);
CREATE INDEX IF NOT EXISTS ix_tacad_treino ON treino_academia(treino_id, ordem);
CREATE INDEX IF NOT EXISTS ix_tcorr_treino ON treino_corrida(treino_id, ordem);
"""

TABELAS = ("usuarios", "macrociclos", "fases", "treinos", "treino_academia", "treino_corrida")

# O app acessa direto pelo Postgres; a API pública do Supabase fica bloqueada.
RLS_PG = "".join(f"""
ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    REVOKE ALL ON {t} FROM anon, authenticated;
  END IF;
END $$;""" for t in TABELAS)


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
            # Trava: os workers do gunicorn sobem juntos; só um cria/altera tabelas por vez.
            conn.execute("SELECT pg_advisory_xact_lock(7701)")
            conn.execute(SCHEMA_PG)
            conn.execute(RLS_PG)
        else:
            conn.executescript(SCHEMA_SQLITE)
        existentes = _colunas_existentes(conn, "usuarios")
        for nome, tipo in COLUNAS_USUARIOS.items():
            if nome not in existentes:
                # IF NOT EXISTS: os workers do gunicorn sobem juntos e podem tentar ao mesmo tempo
                se_nao = "IF NOT EXISTS " if IS_PG else ""
                conn.execute(f"ALTER TABLE usuarios ADD COLUMN {se_nao}{nome} {tipo}")
        conn.commit()
