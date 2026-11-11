"""Professores (administrador), registro do treino pelo aluno e acompanhamento."""
import re
from datetime import date, timedelta

import pytest
from werkzeug.security import generate_password_hash

import db
import registros
from app import app

app.config["TESTING"] = True
SENHA = "senha-forte-1"
HOJE = date.today()
SEG = HOJE - timedelta(days=HOJE.weekday())          # segunda desta semana
INICIO = SEG - timedelta(weeks=2)                     # macrociclo começou há 2 semanas


def _csrf(c, url):
    return re.search(r'name="csrf" value="(\w+)"', c.get(url).text).group(1)


def _login(email, senha=SENHA):
    c = app.test_client()
    c.post("/login", data={"email": email, "senha": senha, "csrf": _csrf(c, "/login")})
    return c


def _usuario(nome, email, perfil, instrutor_id=None, admin=0):
    return db.insert("INSERT INTO usuarios (nome, email, senha_hash, perfil, instrutor_id, admin) VALUES (?, ?, ?, ?, ?, ?)",
                     (nome, email, generate_password_hash(SENHA), perfil, instrutor_id, admin))


def test_ler_tempos_reps():
    assert registros.ler_tempos_reps("72 71 70") == [72, 71, 70]
    assert registros.ler_tempos_reps("1:12, 1:11;70s") == [72, 71, 70]
    assert registros.ler_tempos_reps("3:52 3:50") == [232, 230] and registros.ler_tempos_reps("") == []
    with pytest.raises(ValueError):
        registros.ler_tempos_reps("72 abc")


# ------------------------------------------------------------- professores
def test_professores_admin():
    adm = _usuario("Adm Prof", "r-adm@t.com", "instrutor", admin=1)
    comum = _usuario("Prof Comum", "r-comum@t.com", "instrutor")
    a = _login("r-adm@t.com")
    assert a.get("/instrutor/professores").status_code == 200
    assert _login("r-comum@t.com").get("/instrutor/professores").status_code == 403
    assert "Professores" not in _login("r-comum@t.com").get("/instrutor").text

    tok = _csrf(a, "/instrutor/professores/novo")
    r = a.post("/instrutor/professores/novo", data={"csrf": tok, "nome": "Nova Prof", "email": "r-nova@t.com", "senha": ""})
    senha = re.search(r'class="senha">([^<]+)<', r.text).group(1)
    nova = db.query_one("SELECT * FROM usuarios WHERE email = 'r-nova@t.com'")
    assert nova["perfil"] == "instrutor" and nova["trocar_senha"] == 1 and nova["admin"] == 0
    assert _login("r-nova@t.com", senha).get("/instrutor").headers["Location"].endswith("/trocar-senha")
    assert "Já existe" in a.post("/instrutor/professores/novo", data={"csrf": tok, "nome": "X", "email": "r-comum@t.com"}).text

    # não pode tirar o próprio admin nem se desativar
    r = a.post(f"/instrutor/professores/{adm}", data={"csrf": tok, "nome": "Adm Prof", "email": "r-adm@t.com"})
    assert "próprio acesso de administrador" in r.text
    a.post(f"/instrutor/professores/{adm}/status", data={"csrf": tok})
    assert db.query_one("SELECT ativo FROM usuarios WHERE id = ?", (adm,))["ativo"] == 1

    # promove, transfere alunos e desativa
    a.post(f"/instrutor/professores/{comum}", data={"csrf": tok, "nome": "Prof Comum", "email": "r-comum@t.com", "admin": "1"})
    assert db.query_one("SELECT admin FROM usuarios WHERE id = ?", (comum,))["admin"] == 1
    al = _usuario("Aluno do Comum", "r-al-comum@t.com", "aluno", comum)
    a.post(f"/instrutor/professores/{comum}/transferir", data={"csrf": tok, "destino": str(nova["id"])})
    assert db.query_one("SELECT instrutor_id FROM usuarios WHERE id = ?", (al,))["instrutor_id"] == nova["id"]
    a.post(f"/instrutor/professores/{comum}/status", data={"csrf": tok})
    assert _login("r-comum@t.com").get("/instrutor").status_code == 302          # desativado não entra
    r = a.post(f"/instrutor/professores/{nova['id']}/redefinir-senha", data={"csrf": tok})
    assert "Senha redefinida" in r.text and "Voltar aos professores" in r.text


def test_primeiro_professor_vira_admin(tmp_path, monkeypatch):
    if db.IS_PG:
        pytest.skip("teste do SQLite")
    monkeypatch.setattr(db, "SQLITE_PATH", str(tmp_path / "x.db"))
    db.init_db()
    db.execute("INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES ('A', 'a@x', 'h', 'aluno')")
    db.execute("INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES ('P1', 'p1@x', 'h', 'instrutor')")
    db.execute("INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES ('P2', 'p2@x', 'h', 'instrutor')")
    db.init_db()
    assert [r["email"] for r in db.query_all("SELECT email FROM usuarios WHERE admin = 1")] == ["p1@x"]


# ------------------------------------------------------------- registro e acompanhamento
@pytest.fixture(scope="module")
def ctx():
    p = _usuario("Prof Reg", "r-prof@t.com", "instrutor")
    _usuario("Prof Outro", "r-outro@t.com", "instrutor")
    a = _usuario("Carla Reg", "r-aluno@t.com", "aluno", p)
    _usuario("Outro Aluno", "r-aluno2@t.com", "aluno", p)
    db.execute("INSERT INTO avaliacoes (aluno_id, data, distancia_m, tempo_s, tipo, vdot) VALUES (?, ?, 5000, 1197, 'prova', 50.0)",
               (a, (HOJE - timedelta(days=5)).isoformat()))
    c = _login("r-prof@t.com")
    tok = _csrf(c, f"/instrutor/alunos/{a}/ciclos/novo")
    r = c.post(f"/instrutor/alunos/{a}/ciclos/novo", data={"csrf": tok, "nome": "Ciclo Reg", "data_inicio": INICIO.isoformat(),
                                                           "data_competicao": (INICIO + timedelta(weeks=14)).isoformat(),
                                                           "modelo_corrida": "1", "modelo_academia": "1"})
    mid = int(r.headers["Location"].rsplit("/", 1)[1])

    def corrida(data, blocos):
        f = {"csrf": tok, "modalidade": "corrida", "data": data.isoformat(), "titulo": "Intervalado", "observacoes": "",
             "item_id": [], "tipo": [], "zona": [], "repeticoes": [], "distancia": [], "duracao": [], "pace": [],
             "recuperacao": [], "observacao": []}
        for b in blocos:
            f["item_id"].append(""); [f[k].append(str(b.get(k, ""))) for k in
                                      ("tipo", "zona", "repeticoes", "distancia", "duracao", "pace", "recuperacao", "observacao")]
        c.post(f"/instrutor/ciclos/{mid}/treinos/novo", data=f)
        return db.query_one("SELECT id FROM treinos WHERE macrociclo_id = ? AND data = ? AND modalidade = 'corrida'",
                            (mid, data.isoformat()))["id"]

    def academia(data, exs):
        f = {"csrf": tok, "modalidade": "academia", "data": data.isoformat(), "titulo": "Treino A", "observacoes": "",
             "item_id": [], "exercicio": [], "series": [], "repeticoes": [], "carga": [], "descanso": [], "observacao": []}
        for e in exs:
            f["item_id"].append(""); [f[k].append(str(e.get(k, ""))) for k in ("exercicio", "series", "repeticoes", "carga", "descanso", "observacao")]
        c.post(f"/instrutor/ciclos/{mid}/treinos/novo", data=f)
        return db.query_one("SELECT id FROM treinos WHERE macrociclo_id = ? AND data = ? AND modalidade = 'academia'",
                            (mid, data.isoformat()))["id"]

    ontem = HOJE - timedelta(days=1)
    t_corr = corrida(ontem, [{"tipo": "Aquecimento", "zona": "E", "repeticoes": 1, "distancia": "3"},
                             {"tipo": "Tiros", "zona": "R", "repeticoes": 4, "distancia": "400"}])
    t_acad1 = academia(HOJE - timedelta(days=9), [{"exercicio": "Agachamento", "series": 3, "repeticoes": "10", "carga": "40 kg"}])
    t_acad2 = academia(HOJE - timedelta(days=2), [{"exercicio": "Agachamento", "series": 3, "repeticoes": "8", "carga": "45 kg"},
                                                  {"exercicio": "Remada", "series": 2, "repeticoes": "12"}])
    t_futuro = corrida(HOJE + timedelta(days=2), [{"tipo": "Rodagem", "zona": "E", "repeticoes": 1, "distancia": "8"}])
    return {"c": c, "tok": tok, "mid": mid, "a": a, "t_corr": t_corr, "t_acad1": t_acad1, "t_acad2": t_acad2, "t_futuro": t_futuro}


def _itens(tabela, tid):
    return db.query_all(f"SELECT * FROM {tabela} WHERE treino_id = ? ORDER BY ordem", (tid,))


def test_registro_corrida(ctx):
    al = _login("r-aluno@t.com")
    tid = ctx["t_corr"]
    aq, tiros = _itens("treino_corrida", tid)
    form = al.get(f"/aluno/treinos/{tid}/registro").text
    assert "Tempo de cada repetição" in form and 'value="400 m"' in form and 'data-alvo="' in form
    tok = _csrf(al, f"/aluno/treinos/{tid}/registro")

    r = al.post(f"/aluno/treinos/{tid}/registro", data={"csrf": tok, "status": "feito", f"tempos_{tiros['id']}": "72 abc", f"dist_{tiros['id']}": "400"})
    assert "não entendido" in r.text and 'value="72 abc"' in r.text       # o que foi digitado volta
    r = al.post(f"/aluno/treinos/{tid}/registro", data={"csrf": tok, "status": "feito"})
    assert "Preencha pelo menos um bloco" in r.text

    r = al.post(f"/aluno/treinos/{tid}/registro", data={
        "csrf": tok, "status": "feito", "rpe": "7", "duracao_min": "40", "comentario": "Pernas pesadas",
        f"dist_{aq['id']}": "3 km", f"tempo_{aq['id']}": "16:30",
        f"dist_{tiros['id']}": "400", f"tempos_{tiros['id']}": "86 85 87 84"})
    assert r.status_code == 302
    reg = registros.carregar([tid])[tid]
    assert reg["status"] == "feito" and reg["rpe"] == 7 and reg["duracao_min"] == 40
    assert reg["corrida"][tiros["id"]]["distancia_m"] == 1600 and reg["corrida"][tiros["id"]]["tempo_s"] == 342
    assert reg["corrida"][aq["id"]]["tempo_s"] == 990

    # semana do aluno mostra o status e o professor vê o registro com ritmo x alvo
    sem = al.get(r.headers["Location"].split("#")[0]).text
    assert "✓ Feito" in sem and "Editar registro" in sem
    pv = ctx["c"].get(f"/instrutor/treinos/{tid}/registro").text
    assert "Pernas pesadas" in pv and "Ritmo por bloco" in pv and "3:34/km" in pv   # 342 s / 1,6 km = 213,75 -> 3:34
    assert "Carga interna da sessão: <b>280</b>" in pv                                  # 7 × 40


def test_registro_academia_e_progressao(ctx):
    al = _login("r-aluno@t.com")
    (ag1,) = _itens("treino_academia", ctx["t_acad1"])
    tok = _csrf(al, f"/aluno/treinos/{ctx['t_acad1']}/registro")
    r = al.post(f"/aluno/treinos/{ctx['t_acad1']}/registro", data={
        "csrf": tok, "status": "feito", "rpe": "6", "duracao_min": "50",
        f"carga_{ag1['id']}_1": "40", f"reps_{ag1['id']}_1": "10", f"carga_{ag1['id']}_2": "42,5", f"reps_{ag1['id']}_2": "10",
        f"carga_{ag1['id']}_3": "abc"})
    assert "série 3" in r.text
    al.post(f"/aluno/treinos/{ctx['t_acad1']}/registro", data={
        "csrf": tok, "status": "feito", "rpe": "6", "duracao_min": "50",
        f"carga_{ag1['id']}_1": "40", f"reps_{ag1['id']}_1": "10", f"carga_{ag1['id']}_2": "42,5", f"reps_{ag1['id']}_2": "10",
        f"carga_{ag1['id']}_3": "42,5", f"reps_{ag1['id']}_3": "9"})
    # no treino seguinte aparece a última carga como referência
    ag2, rem = _itens("treino_academia", ctx["t_acad2"])
    form = al.get(f"/aluno/treinos/{ctx['t_acad2']}/registro").text
    assert "Última vez: 42,5 kg × 10" in form
    al.post(f"/aluno/treinos/{ctx['t_acad2']}/registro", data={
        "csrf": tok, "status": "parcial", "rpe": "8",
        f"carga_{ag2['id']}_1": "45", f"reps_{ag2['id']}_1": "8", f"carga_{ag2['id']}_2": "47,5", f"reps_{ag2['id']}_2": "8"})
    prog = {e["nome"]: e for e in registros.progressao_cargas(ctx["a"])}
    assert prog["Agachamento"]["primeira"] == 42.5 and prog["Agachamento"]["ultima"] == 47.5 and prog["Agachamento"]["variacao"] == 12

    # professor edita o treino: o exercício mantido conserva o registro; o removido some
    c, tok_p = ctx["c"], ctx["tok"]
    c.post(f"/instrutor/treinos/{ctx['t_acad2']}", data={
        "csrf": tok_p, "modalidade": "academia", "data": (HOJE - timedelta(days=2)).isoformat(), "titulo": "Treino A", "observacoes": "",
        "item_id": [str(ag2["id"])], "exercicio": ["Agachamento"], "series": ["3"], "repeticoes": ["8"], "carga": ["45 kg"],
        "descanso": [""], "observacao": [""]})
    reg = registros.carregar([ctx["t_acad2"]])[ctx["t_acad2"]]
    assert len(reg["series"][ag2["id"]]) == 2 and rem["id"] not in reg["series"]


def test_registro_regras_de_acesso(ctx):
    al = _login("r-aluno@t.com")
    r = al.get(f"/aluno/treinos/{ctx['t_futuro']}/registro")
    assert r.status_code == 302                                                     # futuro: não registra
    assert _login("r-aluno2@t.com").get(f"/aluno/treinos/{ctx['t_corr']}/registro").status_code == 404
    assert _login("r-outro@t.com").get(f"/instrutor/treinos/{ctx['t_corr']}/registro").status_code == 404
    assert _login("r-outro@t.com").get(f"/instrutor/alunos/{ctx['a']}/acompanhamento").status_code == 404
    assert al.get("/instrutor/acompanhamento").status_code == 403
    # "não feito" dispensa os detalhes
    (aq, _) = _itens("treino_corrida", ctx["t_corr"])
    tok = _csrf(al, f"/aluno/treinos/{ctx['t_corr']}/registro")
    hoje_t = db.insert("INSERT INTO treinos (macrociclo_id, data, modalidade) VALUES (?, ?, 'corrida')", (ctx["mid"], HOJE.isoformat()))
    db.insert("INSERT INTO treino_corrida (treino_id, ordem, tipo, repeticoes, distancia_m) VALUES (?, 1, 'Rodagem', 1, 6000)", (hoje_t,))
    r = al.post(f"/aluno/treinos/{hoje_t}/registro", data={"csrf": tok, "status": "nao_feito", "comentario": "Chuva forte"})
    assert r.status_code == 302 and registros.carregar([hoje_t])[hoje_t]["status"] == "nao_feito"


def test_acompanhamento_professor_e_aluno(ctx):
    c = ctx["c"]
    pag = c.get("/instrutor/acompanhamento").text
    assert "Carla Reg" in pag and "Outro Aluno" in pag and "Sem treinos montados" in pag
    det = c.get(f"/instrutor/alunos/{ctx['a']}/acompanhamento").text
    for trecho in ("Semanas", "Sessões", "Progressão de carga", "Agachamento", "+12%", "Pernas pesadas", "Feito em parte",
                   "Ver registro completo", "Carga interna"):
        assert trecho in det, trecho
    assert "4,6 km" in det                                                          # 3 km + 4 × 400 m
    al = _login("r-aluno@t.com").get("/aluno/acompanhamento").text
    assert "Minha evolução" in al and "Progressão de carga" in al and "Ver registro completo" not in al
    macro = c.get(f"/instrutor/ciclos/{ctx['mid']}").text
    assert 'data-camada="real-vol"' in macro and "Realizado (registros)" in macro


def test_alertas():
    r7 = {"planejadas": 3, "registradas": 0, "adesao": 0, "rpe_medio": None}
    sem = [{"carga_interna": 100}, {"carga_interna": 100}, {"carga_interna": 100}, {"carga_interna": 200}]
    from rotas_acompanhamento import _alertas
    a = _alertas(r7, sem)
    assert "Sem registros nos últimos 7 dias" in a and any("50% acima" in x for x in a) and any("Adesão baixa" in x for x in a)
