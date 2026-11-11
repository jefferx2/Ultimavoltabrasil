"""Camada de banco: SQLite local / Postgres (Supabase) em produção.

Escolha pela variável DATABASE_URL:
  - ausente           -> SQLite em ./ultimavolta.db
  - postgresql://...  -> Postgres
O SQL do app é escrito com '?' como marcador; aqui é traduzido para '%s' no Postgres.

Desempenho: no Postgres as conexões ficam abertas num pool (por processo) e são reaproveitadas.
Dentro de uma requisição web todas as consultas usam a MESMA conexão (aberta só se a página
consultar o banco e devolvida ao pool no fim), em vez de abrir uma conexão por consulta.
"""
import atexit
import contextvars
import os
import time
import sqlite3
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))
SQLITE_PATH = os.environ.get("SQLITE_PATH", os.path.join(os.path.dirname(__file__), "ultimavolta.db"))
POOL_MAX = int(os.environ.get("DB_POOL_MAX", "4"))

if IS_PG:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

_pool = None
_requisicao = contextvars.ContextVar("db_requisicao", default=None)
estatistica = {"conexoes": 0, "consultas": 0}   # usado nos testes de desempenho
_medicao = contextvars.ContextVar("db_medicao", default=None)   # tempo no banco da requisição atual


def iniciar_medicao():
    _medicao.set({"consultas": 0, "segundos": 0.0})


def medicao():
    return _medicao.get()


def _medir(inicio):
    m = _medicao.get()
    if m is not None:
        m["consultas"] += 1
        m["segundos"] += time.perf_counter() - inicio


def _sql(query):
    return query.replace("?", "%s") if IS_PG else query


def _obter_pool():
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            DATABASE_URL, min_size=1, max_size=POOL_MAX, open=True,
            kwargs={"row_factory": dict_row},
            check=ConnectionPool.check_connection,   # descarta conexão derrubada pelo servidor
            max_idle=300, max_lifetime=1800, timeout=15, name="ultimavolta",
        )
        atexit.register(_pool.close)
    return _pool


def connect():
    """Conexão avulsa (fora do pool). Usada na criação das tabelas."""
    estatistica["conexoes"] += 1
    if IS_PG:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def _conexao_nova():
    """Conexão do pool (Postgres) ou arquivo (SQLite); commit/rollback e devolução automáticos."""
    if IS_PG:
        estatistica["conexoes"] += 1
        with _obter_pool().connection() as conn:
            yield conn
        return
    conn = connect()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


class _Requisicao:
    """Guarda a conexão da requisição atual (aberta só no primeiro uso)."""

    def __init__(self):
        self.cm = None
        self.conn = None

    def obter(self):
        if self.conn is None:
            t0 = time.perf_counter()
            self.cm = _conexao_nova()
            self.conn = self.cm.__enter__()
            m = _medicao.get()
            if m is not None:
                m["segundos"] += time.perf_counter() - t0
        return self.conn

    def fechar(self, erro=None):
        if self.cm is not None:
            cm, self.cm, self.conn = self.cm, None, None
            if erro is None:
                cm.__exit__(None, None, None)
            else:
                cm.__exit__(type(erro), erro, erro.__traceback__)


def iniciar_requisicao():
    _requisicao.set(_Requisicao())


def encerrar_requisicao(erro=None):
    req = _requisicao.get()
    _requisicao.set(None)
    if req is not None:
        req.fechar(erro)


@contextmanager
def _conexao():
    req = _requisicao.get()
    if req is not None:
        yield req.obter()        # mesma conexão para toda a requisição
        return
    with _conexao_nova() as conn:
        yield conn


def query_one(query, params=()):
    estatistica["consultas"] += 1
    t0 = time.perf_counter()
    with _conexao() as conn:
        row = conn.execute(_sql(query), params).fetchone()
    _medir(t0)
    return dict(row) if row else None


def query_all(query, params=()):
    estatistica["consultas"] += 1
    t0 = time.perf_counter()
    with _conexao() as conn:
        linhas = [dict(r) for r in conn.execute(_sql(query), params).fetchall()]
    _medir(t0)
    return linhas


def execute(query, params=()):
    estatistica["consultas"] += 1
    t0 = time.perf_counter()
    with _conexao() as conn:
        conn.execute(_sql(query), params)
        conn.commit()
    _medir(t0)


class Transacao:
    """Várias operações numa única transação (tudo ou nada).

    with db.Transacao() as t:
        novo_id = t.insert("INSERT INTO ... VALUES (?, ?)", (a, b))
        t.execute("UPDATE ...", (...))
    """

    def __enter__(self):
        self._cm = _conexao()
        self.conn = self._cm.__enter__()
        self.conn.commit()   # fecha leituras pendentes da requisição: a transação começa limpa
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type:
                self.conn.rollback()
            else:
                self.conn.commit()
        finally:
            self._cm.__exit__(exc_type, exc, tb)
        return False

    def execute(self, query, params=()):
        estatistica["consultas"] += 1
        t0 = time.perf_counter()
        self.conn.execute(_sql(query), params)
        _medir(t0)

    def query_all(self, query, params=()):
        estatistica["consultas"] += 1
        t0 = time.perf_counter()
        linhas = [dict(r) for r in self.conn.execute(_sql(query), params).fetchall()]
        _medir(t0)
        return linhas

    def insert(self, query, params=()):
        estatistica["consultas"] += 1
        t0 = time.perf_counter()
        if IS_PG:
            novo = self.conn.execute(_sql(query) + " RETURNING id", params).fetchone()["id"]
        else:
            novo = self.conn.execute(query, params).lastrowid
        _medir(t0)
        return novo


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
CREATE TABLE IF NOT EXISTS avaliacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aluno_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    distancia_m INTEGER NOT NULL CHECK (distancia_m BETWEEN 400 and 50000),
    tempo_s INTEGER NOT NULL CHECK (tempo_s > 0),
    tipo TEXT NOT NULL CHECK (tipo IN ('prova', 'teste')),
    descricao TEXT,
    vdot REAL NOT NULL,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_aval_aluno ON avaliacoes(aluno_id, data);
CREATE TABLE IF NOT EXISTS registros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    treino_id INTEGER NOT NULL UNIQUE REFERENCES treinos(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('feito', 'parcial', 'nao_feito')),
    data_realizada TEXT,
    duracao_min INTEGER CHECK (duracao_min IS NULL OR duracao_min BETWEEN 1 AND 600),
    rpe INTEGER CHECK (rpe IS NULL OR rpe BETWEEN 1 AND 10),
    comentario TEXT,
    atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS registro_corrida (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    registro_id INTEGER NOT NULL REFERENCES registros(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES treino_corrida(id) ON DELETE CASCADE,
    distancia_m INTEGER,
    tempo_s REAL,
    tempos_reps TEXT,
    UNIQUE (registro_id, item_id)
);
CREATE TABLE IF NOT EXISTS registro_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    registro_id INTEGER NOT NULL REFERENCES registros(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES treino_academia(id) ON DELETE CASCADE,
    serie INTEGER NOT NULL,
    carga_kg REAL,
    reps INTEGER,
    UNIQUE (registro_id, item_id, serie)
);
CREATE INDEX IF NOT EXISTS ix_regc_item ON registro_corrida(item_id);
CREATE INDEX IF NOT EXISTS ix_regs_item ON registro_series(item_id);
CREATE TABLE IF NOT EXISTS vinculos (
    aluno_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    professor_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    PRIMARY KEY (aluno_id, professor_id)
);
CREATE INDEX IF NOT EXISTS ix_vinc_prof ON vinculos(professor_id);
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
CREATE TABLE IF NOT EXISTS avaliacoes (
    id SERIAL PRIMARY KEY,
    aluno_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    distancia_m INTEGER NOT NULL CHECK (distancia_m BETWEEN 400 and 50000),
    tempo_s INTEGER NOT NULL CHECK (tempo_s > 0),
    tipo TEXT NOT NULL CHECK (tipo IN ('prova', 'teste')),
    descricao TEXT,
    vdot REAL NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_aval_aluno ON avaliacoes(aluno_id, data);
CREATE TABLE IF NOT EXISTS registros (
    id SERIAL PRIMARY KEY,
    treino_id INTEGER NOT NULL UNIQUE REFERENCES treinos(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('feito', 'parcial', 'nao_feito')),
    data_realizada TEXT,
    duracao_min INTEGER CHECK (duracao_min IS NULL OR duracao_min BETWEEN 1 AND 600),
    rpe INTEGER CHECK (rpe IS NULL OR rpe BETWEEN 1 AND 10),
    comentario TEXT,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS registro_corrida (
    id SERIAL PRIMARY KEY,
    registro_id INTEGER NOT NULL REFERENCES registros(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES treino_corrida(id) ON DELETE CASCADE,
    distancia_m INTEGER,
    tempo_s REAL,
    tempos_reps TEXT,
    UNIQUE (registro_id, item_id)
);
CREATE TABLE IF NOT EXISTS registro_series (
    id SERIAL PRIMARY KEY,
    registro_id INTEGER NOT NULL REFERENCES registros(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES treino_academia(id) ON DELETE CASCADE,
    serie INTEGER NOT NULL,
    carga_kg REAL,
    reps INTEGER,
    UNIQUE (registro_id, item_id, serie)
);
CREATE INDEX IF NOT EXISTS ix_regc_item ON registro_corrida(item_id);
CREATE INDEX IF NOT EXISTS ix_regs_item ON registro_series(item_id);
CREATE TABLE IF NOT EXISTS vinculos (
    aluno_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    professor_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    PRIMARY KEY (aluno_id, professor_id)
);
CREATE INDEX IF NOT EXISTS ix_vinc_prof ON vinculos(professor_id);
"""

TABELAS = ("usuarios", "macrociclos", "fases", "treinos", "treino_academia", "treino_corrida", "avaliacoes",
           "registros", "registro_corrida", "registro_series", "vinculos")

# O app acessa direto pelo Postgres; a API pública do Supabase fica bloqueada.
RLS_PG = "".join(f"""
ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    REVOKE ALL ON {t} FROM anon, authenticated;
  END IF;
END $$;""" for t in TABELAS)


# Colunas acrescentadas depois da criação das tabelas (aplicadas em bancos já existentes).
# tabela -> {nome: tipo} (o mesmo nos dois bancos)
COLUNAS_NOVAS = {
    "usuarios": {
        "instrutor_id": "INTEGER REFERENCES usuarios(id)",
        "data_nascimento": "TEXT",
        "prova_principal": "TEXT",
        "telefone": "TEXT",
        "observacoes": "TEXT",
        "trocar_senha": "INTEGER NOT NULL DEFAULT 0",
        "admin": "INTEGER NOT NULL DEFAULT 0",   # professor administrador: cadastra outros professores
        # anamnese (Jack Daniels)
        "prova_categoria": "TEXT",       # chave de daniels.FAIXAS
        "nivel": "TEXT",                 # baixa / media / alta (escolhido pelo professor)
        "volume_atual_km": "REAL",       # média de km/semana nas últimas 4 semanas
        "dias_semana": "INTEGER",        # dias disponíveis para treinar
    },
    "treino_corrida": {
        "zona": "TEXT",                  # E / M / T / I / R
    },
    "macrociclos": {
        "ref_km_semana": "REAL",        # km/semana equivalentes ao volume 5 (corrida)
        "ref_series_semana": "INTEGER",  # séries/semana equivalentes ao volume 5 (academia)
    },
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
        for tabela, colunas in COLUNAS_NOVAS.items():
            existentes = _colunas_existentes(conn, tabela)
            for nome, tipo in colunas.items():
                if nome not in existentes:
                    # IF NOT EXISTS: os workers do gunicorn sobem juntos e podem tentar ao mesmo tempo
                    se_nao = "IF NOT EXISTS " if IS_PG else ""
                    conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {se_nao}{nome} {tipo}")
        # Sem nenhum administrador, o primeiro professor cadastrado passa a ser
        conn.execute("UPDATE usuarios SET admin = 1 WHERE id = (SELECT MIN(id) FROM usuarios WHERE perfil = 'instrutor') "
                     "AND NOT EXISTS (SELECT 1 FROM usuarios WHERE admin = 1)")
        conn.commit()
