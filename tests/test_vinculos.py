"""Aluno vinculado a vários professores: vincular, transferir, desvincular e acesso."""
import re
from datetime import date

import pytest
from werkzeug.security import generate_password_hash

import db
import vinculos
from app import app

app.config["TESTING"] = True
SENHA = "senha-forte-1"


def _csrf(c, url):
    return re.search(r'name="csrf" value="(\w+)"', c.get(url).text).group(1)


def _login(email):
    c = app.test_client()
    c.post("/login", data={"email": email, "senha": SENHA, "csrf": _csrf(c, "/login")})
    return c


def _u(nome, email, perfil, instrutor_id=None, admin=0):
    return db.insert("INSERT INTO usuarios (nome, email, senha_hash, perfil, instrutor_id, admin) VALUES (?, ?, ?, ?, ?, ?)",
                     (nome, email, generate_password_hash(SENHA), perfil, instrutor_id, admin))


@pytest.fixture(scope="module")
def ctx():
    adm = _u("Adm V", "v-adm@t.com", "instrutor", admin=1)
    p2 = _u("Prof V2", "v-p2@t.com", "instrutor")
    p3 = _u("Prof V3", "v-p3@t.com", "instrutor")
    a1 = _u("Aluno V1", "v-a1@t.com", "aluno", adm)
    a2 = _u("Aluno V2", "v-a2@t.com", "aluno", adm)
    mid = db.insert("INSERT INTO macrociclos (aluno_id, nome, data_inicio) VALUES (?, 'Ciclo V', ?)", (a1, date.today().isoformat()))
    return {"adm": adm, "p2": p2, "p3": p3, "a1": a1, "a2": a2, "mid": mid}


def _profs(aid):
    return [(p["nome"], p["principal"]) for p in vinculos.professores_do_aluno(aid)]


def test_regras_de_vinculo(ctx):
    a2, adm, p2, p3 = ctx["a2"], ctx["adm"], ctx["p2"], ctx["p3"]
    assert vinculos.vincular(a2, p2) and not vinculos.vincular(a2, p2) and not vinculos.vincular(a2, adm)
    assert _profs(a2) == [("Adm V", True), ("Prof V2", False)]
    assert vinculos.desvincular(a2, adm) is None                         # sai o principal -> o outro assume
    assert _profs(a2) == [("Prof V2", True)]
    assert "pelo menos um professor" in vinculos.desvincular(a2, p2)       # nunca fica sem professor
    vinculos.vincular(a2, p3)
    vinculos.transferir(a2, adm)                                           # transferir = único professor
    assert _profs(a2) == [("Adm V", True)]
    vinculos.vincular(a2, p2)
    assert vinculos.substituir(p2, p3) == 1 and _profs(a2) == [("Adm V", True), ("Prof V3", False)]
    vinculos.transferir(a2, adm)


def test_professor_vinculado_ve_e_acompanha(ctx):
    a1, p2 = ctx["a1"], ctx["p2"]
    c2 = _login("v-p2@t.com")
    paginas = [f"/instrutor/alunos/{a1}", f"/instrutor/ciclos/{ctx['mid']}", f"/instrutor/alunos/{a1}/acompanhamento"]
    assert all(c2.get(u).status_code == 404 for u in paginas)
    assert "Aluno V1" not in c2.get("/instrutor/alunos").text

    adm = _login("v-adm@t.com")
    tok = _csrf(adm, f"/instrutor/professores/{p2}")
    r = adm.post(f"/instrutor/professores/{p2}/alunos", data={"csrf": tok, "aluno_ids": [str(a1)], "modo": "vincular"})
    assert r.status_code == 302 and _profs(a1) == [("Adm V", True), ("Prof V2", False)]
    assert all(c2.get(u).status_code == 200 for u in paginas)
    assert "Aluno V1" in c2.get("/instrutor/alunos").text and "Aluno V1" in c2.get("/instrutor/acompanhamento").text
    assert "Aluno V1" in adm.get("/instrutor/alunos").text                # o principal continua vendo
    ficha = adm.get(f"/instrutor/alunos/{a1}").text
    assert "Prof V2" in ficha and "Principal" in ficha

    # desvincular pela ficha do aluno
    adm.post(f"/instrutor/professores/{p2}/alunos/{a1}/remover", data={"csrf": tok, "voltar": "aluno"})
    assert c2.get(f"/instrutor/alunos/{a1}").status_code == 404
    # desvincular o único professor é recusado
    r = adm.post(f"/instrutor/professores/{ctx['adm']}/alunos/{a1}/remover", data={"csrf": tok}, follow_redirects=True)
    assert "pelo menos um professor" in r.text and _profs(a1) == [("Adm V", True)]


def test_novo_professor_ja_com_alunos(ctx):
    adm = _login("v-adm@t.com")
    tok = _csrf(adm, "/instrutor/professores/novo")
    form = adm.get("/instrutor/professores/novo").text
    assert "Aluno V1" in form and "com Adm V" in form and 'value="transferir"' in form
    adm.post("/instrutor/professores/novo", data={"csrf": tok, "nome": "Prof Nova V", "email": "v-nova@t.com",
                                                 "aluno_ids": [str(ctx["a2"])], "modo": "transferir"})
    nova = db.query_one("SELECT id FROM usuarios WHERE email = 'v-nova@t.com'")["id"]
    assert _profs(ctx["a2"]) == [("Prof Nova V", True)]
    adm.post("/instrutor/professores/novo", data={"csrf": tok, "nome": "Prof Mais V", "email": "v-mais@t.com",
                                                 "aluno_ids": [str(ctx["a1"])], "modo": "vincular"})
    assert [n for n, _ in _profs(ctx["a1"])] == ["Adm V", "Prof Mais V"]
    # pela ficha do aluno: vincular e transferir
    adm.post(f"/instrutor/alunos/{ctx['a1']}/professores", data={"csrf": tok, "professor_id": str(ctx["p3"]), "modo": "vincular"})
    assert "Prof V3" in [n for n, _ in _profs(ctx["a1"])]
    r = adm.post(f"/instrutor/alunos/{ctx['a2']}/professores", data={"csrf": tok, "professor_id": str(nova), "modo": "transferir"})
    assert r.status_code == 302


def test_so_administrador_mexe_em_vinculos(ctx):
    c2 = _login("v-p2@t.com")
    tok = _csrf(c2, "/instrutor/alunos/novo")
    assert c2.post(f"/instrutor/professores/{ctx['p2']}/alunos", data={"csrf": tok, "aluno_ids": [str(ctx["a1"])]}).status_code == 403
    assert c2.post(f"/instrutor/alunos/{ctx['a1']}/professores", data={"csrf": tok, "professor_id": str(ctx["p2"])}).status_code == 403
    assert c2.post(f"/instrutor/professores/{ctx['adm']}/alunos/{ctx['a1']}/remover", data={"csrf": tok}).status_code == 403
