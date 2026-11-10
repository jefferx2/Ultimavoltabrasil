import re

import pytest
from werkzeug.security import generate_password_hash

import db
from app import app

app.config["TESTING"] = True


def _csrf(client, url="/login"):
    return re.search(r'name="csrf" value="(\w+)"', client.get(url).text).group(1)


def _login(client, email, senha):
    return client.post("/login", data={"email": email, "senha": senha, "csrf": _csrf(client)})


def _criar(nome, email, perfil, senha="senha-forte-1", instrutor_id=None, trocar=0):
    db.execute("INSERT INTO usuarios (nome, email, senha_hash, perfil, instrutor_id, trocar_senha) "
               "VALUES (?, ?, ?, ?, ?, ?)",
               (nome, email, generate_password_hash(senha), perfil, instrutor_id, trocar))
    return db.query_one("SELECT id FROM usuarios WHERE email = ?", (email,))["id"]


@pytest.fixture(scope="module")
def professores():
    p1 = _criar("Prof Um", "prof1@t.com", "instrutor")
    p2 = _criar("Prof Dois", "prof2@t.com", "instrutor")
    return p1, p2


def test_cadastro_completo_e_primeiro_acesso(professores):
    c = app.test_client()
    assert _login(c, "prof1@t.com", "senha-forte-1").headers["Location"] == "/instrutor"

    tok = _csrf(c, "/instrutor/alunos/novo")
    r = c.post("/instrutor/alunos/novo", data={
        "csrf": tok, "nome": "D'Ana Brien", "email": "  ANA@t.com ", "data_nascimento": "1990-05-10",
        "prova_principal": "800 m", "telefone": "11 99999-0000", "observacoes": "Joelho direito", "senha": ""})
    assert r.status_code == 200 and "Aluno cadastrado" in r.text
    senha = re.search(r'class="senha">([^<]+)<', r.text).group(1)
    assert len(senha) == 10
    assert "Ol\\u00e1, D\\u0027Ana!" in r.text  # apóstrofo escapado: não quebra o JS

    aluno = db.query_one("SELECT * FROM usuarios WHERE email = 'ana@t.com'")
    assert aluno["instrutor_id"] == professores[0] and aluno["trocar_senha"] == 1
    assert aluno["prova_principal"] == "800 m" and aluno["data_nascimento"] == "1990-05-10"

    lista = c.get("/instrutor/alunos").text
    assert "D&#39;Ana Brien" in lista and "Aguardando 1º acesso" in lista

    # aluno entra -> é obrigado a trocar a senha antes de qualquer coisa
    a = app.test_client()
    assert _login(a, "ana@t.com", senha).headers["Location"] == "/trocar-senha"
    assert a.get("/aluno").headers["Location"] == "/trocar-senha"
    tok = _csrf(a, "/trocar-senha")
    r = a.post("/trocar-senha", data={"csrf": tok, "atual": senha, "nova": "curta", "confirmacao": "curta"})
    assert "pelo menos 8" in r.text
    r = a.post("/trocar-senha", data={"csrf": tok, "atual": senha, "nova": "minhasenha9", "confirmacao": "outra"})
    assert "não confere" in r.text
    r = a.post("/trocar-senha", data={"csrf": tok, "atual": "errada", "nova": "minhasenha9", "confirmacao": "minhasenha9"})
    assert "atual incorreta" in r.text
    r = a.post("/trocar-senha", data={"csrf": tok, "atual": senha, "nova": "minhasenha9", "confirmacao": "minhasenha9"})
    assert r.headers["Location"] == "/aluno"
    assert a.get("/aluno").status_code == 200

    # senha provisória não vale mais; a nova vale
    assert _login(app.test_client(), "ana@t.com", senha).status_code == 200
    assert _login(app.test_client(), "ana@t.com", "minhasenha9").headers["Location"] == "/aluno"


def test_validacoes(professores):
    c = app.test_client()
    _login(c, "prof1@t.com", "senha-forte-1")
    tok = _csrf(c, "/instrutor/alunos/novo")
    r = c.post("/instrutor/alunos/novo", data={"csrf": tok, "nome": "", "email": "sem-arroba"})
    assert "Informe o nome" in r.text and "e-mail válido" in r.text
    r = c.post("/instrutor/alunos/novo", data={"csrf": tok, "nome": "X", "email": "prof2@t.com"})
    assert "Já existe" in r.text
    r = c.post("/instrutor/alunos/novo", data={"csrf": tok, "nome": "X", "email": "x@t.com", "data_nascimento": "2999-01-01"})
    assert "futuro" in r.text
    r = c.post("/instrutor/alunos/novo", data={"csrf": tok, "nome": "X", "email": "x@t.com", "senha": "123"})
    assert "pelo menos 8" in r.text
    assert db.query_one("SELECT id FROM usuarios WHERE email = 'x@t.com'") is None
    # senha definida pelo professor é aceita
    r = c.post("/instrutor/alunos/novo", data={"csrf": tok, "nome": "Xis", "email": "x@t.com", "senha": "definida123"})
    assert "definida123" in r.text


def test_editar_redefinir_desativar(professores):
    p1, _ = professores
    aid = _criar("Bruno", "bruno@t.com", "aluno", senha="brunosenha1", instrutor_id=p1)
    c = app.test_client()
    _login(c, "prof1@t.com", "senha-forte-1")
    tok = _csrf(c, f"/instrutor/alunos/{aid}")

    r = c.post(f"/instrutor/alunos/{aid}", data={"csrf": tok, "nome": "Bruno Lima", "email": "bruno@t.com",
                                                  "prova_principal": "1500 m", "data_nascimento": ""})
    assert r.status_code == 302
    b = db.query_one("SELECT * FROM usuarios WHERE id = ?", (aid,))
    assert b["nome"] == "Bruno Lima" and b["prova_principal"] == "1500 m" and b["data_nascimento"] is None

    # e-mail de outro usuário é recusado na edição
    r = c.post(f"/instrutor/alunos/{aid}", data={"csrf": tok, "nome": "Bruno Lima", "email": "ana@t.com"})
    assert "Já existe" in r.text

    r = c.post(f"/instrutor/alunos/{aid}/redefinir-senha", data={"csrf": tok})
    nova = re.search(r'class="senha">([^<]+)<', r.text).group(1)
    assert _login(app.test_client(), "bruno@t.com", "brunosenha1").status_code == 200  # antiga não vale
    assert _login(app.test_client(), "bruno@t.com", nova).headers["Location"] == "/trocar-senha"

    c.post(f"/instrutor/alunos/{aid}/status", data={"csrf": tok})
    assert _login(app.test_client(), "bruno@t.com", nova).status_code == 200  # inativo não entra
    assert "<b>Bruno Lima</b>" not in c.get("/instrutor/alunos").text
    assert "<b>Bruno Lima</b>" in c.get("/instrutor/alunos?mostrar=todos").text
    c.post(f"/instrutor/alunos/{aid}/status", data={"csrf": tok})
    assert _login(app.test_client(), "bruno@t.com", nova).headers["Location"] == "/trocar-senha"


def test_isolamento_entre_professores_e_perfis(professores):
    p1, p2 = professores
    aid = _criar("Carla", "carla@t.com", "aluno", instrutor_id=p1)

    c2 = app.test_client()
    _login(c2, "prof2@t.com", "senha-forte-1")
    assert "Carla" not in c2.get("/instrutor/alunos?mostrar=todos").text
    assert c2.get(f"/instrutor/alunos/{aid}").status_code == 404
    tok = _csrf(c2, "/instrutor/alunos/novo")
    assert c2.post(f"/instrutor/alunos/{aid}/redefinir-senha", data={"csrf": tok}).status_code == 404
    assert c2.post(f"/instrutor/alunos/{aid}/status", data={"csrf": tok}).status_code == 404

    a = app.test_client()
    _login(a, "carla@t.com", "senha-forte-1")
    assert a.get("/instrutor/alunos").status_code == 403
    assert a.get(f"/instrutor/alunos/{aid}").status_code == 403

    anon = app.test_client()
    assert anon.get("/instrutor/alunos").status_code == 302
    # POST sem token CSRF é recusado (c2 continua logado)
    assert c2.post("/instrutor/alunos/novo", data={"nome": "Z", "email": "z@t.com"}).status_code == 400


def test_troca_voluntaria_de_senha(professores):
    c = app.test_client()
    _login(c, "prof1@t.com", "senha-forte-1")
    tok = _csrf(c, "/trocar-senha")
    r = c.post("/trocar-senha", data={"csrf": tok, "atual": "senha-forte-1", "nova": "senha-forte-2", "confirmacao": "senha-forte-2"})
    assert r.headers["Location"] == "/instrutor"
    assert _login(app.test_client(), "prof1@t.com", "senha-forte-2").headers["Location"] == "/instrutor"


def test_painel_mostra_total(professores):
    c = app.test_client()
    _login(c, "prof1@t.com", "senha-forte-2")
    ativos = db.query_one("SELECT COUNT(*) AS n FROM usuarios WHERE perfil='aluno' AND ativo=1 AND instrutor_id=?",
                          (professores[0],))["n"]
    assert f'<span class="numero">{ativos}</span>' in c.get("/instrutor").text
