import re
from datetime import date, timedelta

import pytest
from werkzeug.security import generate_password_hash

import db
import treinos
from app import app

app.config["TESTING"] = True
SENHA = "senha-forte-1"
INICIO = date(2026, 11, 16)          # segunda-feira
COMP = date(2027, 4, 10)


def _csrf(c, url):
    return re.search(r'name="csrf" value="(\w+)"', c.get(url).text).group(1)


def _login(email):
    c = app.test_client()
    c.post("/login", data={"email": email, "senha": SENHA, "csrf": _csrf(c, "/login")})
    return c


def _criar(nome, email, perfil, instrutor_id=None):
    return db.insert("INSERT INTO usuarios (nome, email, senha_hash, perfil, instrutor_id) VALUES (?, ?, ?, ?, ?)",
                     (nome, email, generate_password_hash(SENHA), perfil, instrutor_id))


@pytest.fixture(scope="module")
def ctx():
    p1 = _criar("Prof T1", "t-prof1@t.com", "instrutor")
    _criar("Prof T2", "t-prof2@t.com", "instrutor")
    a1 = _criar("Aluno T1", "t-aluno1@t.com", "aluno", p1)
    _criar("Aluno T2", "t-aluno2@t.com", "aluno", p1)
    c = _login("t-prof1@t.com")
    tok = _csrf(c, f"/instrutor/alunos/{a1}/ciclos/novo")
    r = c.post(f"/instrutor/alunos/{a1}/ciclos/novo", data={
        "csrf": tok, "nome": "Temporada", "data_inicio": INICIO.isoformat(), "data_competicao": COMP.isoformat(),
        "modelo_academia": "1", "modelo_corrida": "1"})
    mid = int(r.headers["Location"].rsplit("/", 1)[1])
    return {"c": c, "tok": tok, "mid": mid, "a1": a1}


def _post_corrida(ctx, data, blocos, **extra):
    form = {"csrf": ctx["tok"], "modalidade": "corrida", "data": data, "titulo": extra.get("titulo", "Intervalado"),
            "observacoes": "", "item_id": [], "tipo": [], "repeticoes": [], "distancia": [], "duracao": [],
            "pace": [], "recuperacao": [], "observacao": []}
    for b in blocos:
        form["item_id"].append(str(b.get("id", "")))
        for k in ("tipo", "repeticoes", "distancia", "duracao", "pace", "recuperacao", "observacao"):
            form[k].append(str(b.get(k, "")))
    url = extra.get("url", f"/instrutor/ciclos/{ctx['mid']}/treinos/novo")
    return ctx["c"].post(url, data=form)


def _post_academia(ctx, data, exercicios, url=None):
    form = {"csrf": ctx["tok"], "modalidade": "academia", "data": data, "titulo": "Treino A", "observacoes": "Técnica",
            "item_id": [], "exercicio": [], "series": [], "repeticoes": [], "carga": [], "descanso": [], "observacao": []}
    for e in exercicios:
        form["item_id"].append(str(e.get("id", "")))
        for k in ("exercicio", "series", "repeticoes", "carga", "descanso", "observacao"):
            form[k].append(str(e.get(k, "")))
    return ctx["c"].post(url or f"/instrutor/ciclos/{ctx['mid']}/treinos/novo", data=form)


# ------------------------------------------------------------- utilidades
@pytest.mark.parametrize("txt,m", [("400", 400), ("400m", 400), ("1,5 km", 1500), ("8km", 8000), ("8", 8000),
                                   ("100", 100), ("", None), ("12.5k", 12500)])
def test_ler_distancia(txt, m):
    assert treinos.ler_distancia(txt) == m


@pytest.mark.parametrize("txt", ["0", "abc", "200 km", "-5", "4 voltas"])
def test_ler_distancia_invalida(txt):
    with pytest.raises(ValueError):
        treinos.ler_distancia(txt)


def test_fmt_distancia():
    assert [treinos.fmt_distancia(x) for x in (400, 1000, 1500, 12500, 21097, None)] == \
        ["400 m", "1 km", "1,5 km", "12,5 km", "21,1 km", ""]


# ------------------------------------------------------------- telas
def test_semana_redireciona_e_navega(ctx):
    c, mid = ctx["c"], ctx["mid"]
    r = c.get(f"/instrutor/ciclos/{mid}/semanas")
    assert r.status_code == 302 and "/semanas/" in r.headers["Location"]
    pag = c.get(f"/instrutor/ciclos/{mid}/semanas/1").text
    assert "Semana 1" in pag and "16/11/2026 a 22/11/2026" in pag and "Endurance-Hipertrofia" in pag
    assert "Base Aeróbica" in pag and "+ Corrida" in pag and "Semana 2 ▶" in pag
    assert c.get(f"/instrutor/ciclos/{mid}/semanas/0").status_code == 404
    assert c.get(f"/instrutor/ciclos/{mid}/semanas/999").status_code == 404


def test_form_academia_sugere_series_da_fase(ctx):
    pag = ctx["c"].get(f"/instrutor/ciclos/{ctx['mid']}/treinos/novo?modalidade=academia&data=2026-11-17").text
    assert "Endurance-Hipertrofia" in pag and "sugestão 3–5 séries × 15–20 reps" in pag
    assert 'name="series" type="number" min="1" max="20" value="3"' in pag
    assert 'name="repeticoes" value="15–20"' in pag
    assert ctx["c"].get(f"/instrutor/ciclos/{ctx['mid']}/treinos/novo?modalidade=yoga").status_code == 404


def test_criar_corrida_e_resumo(ctx):
    r = _post_corrida(ctx, "2026-11-18", [
        {"tipo": "Aquecimento", "repeticoes": 1, "duracao": "15 min"},
        {"tipo": "Tiros", "repeticoes": 6, "distancia": "400", "pace": "68 s", "recuperacao": "2 min"},
        {"tipo": "Desaquecimento", "repeticoes": 1, "distancia": "2 km"},
        {"tipo": "", "repeticoes": 1},                                         # linha vazia: ignorada
    ])
    assert r.status_code == 302 and r.headers["Location"].endswith("/semanas/1#d2026-11-18")
    t = db.query_one("SELECT * FROM treinos WHERE macrociclo_id = ? AND data = '2026-11-18'", (ctx["mid"],))
    blocos = db.query_all("SELECT * FROM treino_corrida WHERE treino_id = ? ORDER BY ordem", (t["id"],))
    assert [(b["tipo"], b["repeticoes"], b["distancia_m"]) for b in blocos] == \
        [("Aquecimento", 1, None), ("Tiros", 6, 400), ("Desaquecimento", 1, 2000)]
    pag = ctx["c"].get(f"/instrutor/ciclos/{ctx['mid']}/semanas/1").text
    assert "Tiros</b> 6× 400 m" in pag and "@ 68 s" in pag and "4,4 km" in pag   # 6x400 + 2000


def test_validacoes(ctx):
    r = _post_corrida(ctx, "2026-11-19", [{"tipo": "Rodagem", "repeticoes": 1}])
    assert "informe a distância ou a duração" in r.text
    r = _post_corrida(ctx, "2026-11-19", [{"tipo": "Rodagem", "repeticoes": 1, "distancia": "4 voltas"}])
    assert "não entendida" in r.text
    r = _post_corrida(ctx, "2026-11-19", [{"tipo": "Tiros", "repeticoes": 0, "distancia": "400"}])
    assert "repetições deve ser" in r.text
    r = _post_corrida(ctx, "2026-11-19", [{"tipo": "", "repeticoes": 1, "distancia": "5"}])
    assert "escolha o tipo" in r.text
    r = _post_corrida(ctx, "2026-11-19", [])
    assert "pelo menos um bloco" in r.text
    r = _post_academia(ctx, "2026-11-19", [{"exercicio": "Supino", "series": "0"}, {"exercicio": "", "series": "3", "carga": "20"}])
    assert "séries deve ser" in r.text and "Exercício 2: informe o nome" in r.text
    r = _post_corrida(ctx, "2026-11-01", [{"tipo": "Rodagem", "repeticoes": 1, "distancia": "5"}])
    assert "precisa estar entre 16/11/2026" in r.text
    r = _post_corrida(ctx, "2030-01-01", [{"tipo": "Rodagem", "repeticoes": 1, "distancia": "5"}])
    assert "precisa estar entre" in r.text
    assert db.query_one("SELECT COUNT(*) AS n FROM treinos WHERE data IN ('2026-11-19','2026-11-01','2030-01-01')")["n"] == 0
    # os dados digitados voltam no formulário
    assert 'value="Supino"' in _post_academia(ctx, "2026-11-19", [{"exercicio": "Supino", "series": "0"}]).text


def test_editar_preserva_ids(ctx):
    r = _post_academia(ctx, "2026-11-20", [
        {"exercicio": "Agachamento", "series": "4", "repeticoes": "15", "carga": "40 kg", "descanso": "60 s"},
        {"exercicio": "Remada", "series": "3", "repeticoes": "15"},
        {"exercicio": "Prancha", "series": "3", "repeticoes": "30 s"},
    ])
    assert r.status_code == 302
    tid = db.query_one("SELECT id FROM treinos WHERE data = '2026-11-20'")["id"]
    ag, rem, pr = db.query_all("SELECT * FROM treino_academia WHERE treino_id = ? ORDER BY ordem", (tid,))

    # outro treino de academia, para tentar "roubar" o id de um exercício dele
    _post_academia(ctx, "2026-11-22", [{"exercicio": "Supino", "series": "3", "repeticoes": "10"}])
    alheio = db.query_one("SELECT a.id FROM treino_academia a JOIN treinos t ON t.id = a.treino_id WHERE t.data = '2026-11-22'")["id"]

    # edita: muda o agachamento, remove a remada, inverte ordem, adiciona um novo e tenta usar um id alheio
    r = _post_academia(ctx, "2026-11-20", [
        {"id": pr["id"], "exercicio": "Prancha", "series": "3", "repeticoes": "45 s"},
        {"id": ag["id"], "exercicio": "Agachamento", "series": "5", "repeticoes": "12", "carga": "45 kg"},
        {"exercicio": "Afundo", "series": "3", "repeticoes": "10"},
        {"id": alheio, "exercicio": "Stiff", "series": "3", "repeticoes": "12"},
    ], url=f"/instrutor/treinos/{tid}")
    assert r.status_code == 302
    novos = db.query_all("SELECT * FROM treino_academia WHERE treino_id = ? ORDER BY ordem", (tid,))
    assert [(x["exercicio"], x["series"]) for x in novos] == [("Prancha", 3), ("Agachamento", 5), ("Afundo", 3), ("Stiff", 3)]
    assert novos[0]["id"] == pr["id"] and novos[1]["id"] == ag["id"]          # ids mantidos
    assert rem["id"] not in {x["id"] for x in novos}                          # removido
    assert alheio not in {x["id"] for x in novos}                             # id alheio virou item novo
    assert db.query_one("SELECT exercicio FROM treino_academia WHERE id = ?", (alheio,))["exercicio"] == "Supino"  # intacto
    # sugestão de exercícios usados
    pag = ctx["c"].get(f"/instrutor/treinos/{tid}").text
    assert '<option value="Agachamento">' in pag and 'value="45 kg"' in pag


def test_duplicar_copiar_semana_e_excluir(ctx):
    c, mid, tok = ctx["c"], ctx["mid"], ctx["tok"]
    tid = db.query_one("SELECT id FROM treinos WHERE data = '2026-11-18'")["id"]
    r = c.post(f"/instrutor/treinos/{tid}/duplicar", data={"csrf": tok, "data": "2026-11-25"})
    assert r.headers["Location"].endswith("/semanas/2#d2026-11-25")
    copia = db.query_one("SELECT id FROM treinos WHERE data = '2026-11-25'")["id"]
    assert db.query_one("SELECT COUNT(*) AS n FROM treino_corrida WHERE treino_id = ?", (copia,))["n"] == 3
    r = c.post(f"/instrutor/treinos/{tid}/duplicar", data={"csrf": tok, "data": "2031-01-01"})
    assert db.query_one("SELECT COUNT(*) AS n FROM treinos WHERE data = '2031-01-01'")["n"] == 0

    n_sem1 = db.query_one("SELECT COUNT(*) AS n FROM treinos WHERE macrociclo_id = ? AND data BETWEEN '2026-11-16' AND '2026-11-22'", (mid,))["n"]
    r = c.post(f"/instrutor/ciclos/{mid}/semanas/1/copiar", data={"csrf": tok, "destino": "4"})
    assert r.headers["Location"].endswith("/semanas/4")
    sem4 = db.query_all("SELECT data FROM treinos WHERE macrociclo_id = ? AND data BETWEEN '2026-12-07' AND '2026-12-13' ORDER BY data", (mid,))
    assert len(sem4) == n_sem1 and sem4[0]["data"] == "2026-12-09"           # quarta continua quarta
    assert c.post(f"/instrutor/ciclos/{mid}/semanas/1/copiar", data={"csrf": tok, "destino": "1"}).headers["Location"].endswith("/semanas/1")
    assert c.post(f"/instrutor/ciclos/{mid}/semanas/1/copiar", data={"csrf": tok, "destino": "x"}).status_code == 302
    r = c.post(f"/instrutor/ciclos/{mid}/semanas/10/copiar", data={"csrf": tok, "destino": "11"})
    assert "não tem treinos" in c.get(r.headers["Location"]).text

    c.post(f"/instrutor/treinos/{copia}/excluir", data={"csrf": tok})
    assert db.query_one("SELECT id FROM treinos WHERE id = ?", (copia,)) is None
    assert db.query_one("SELECT COUNT(*) AS n FROM treino_corrida WHERE treino_id = ?", (copia,))["n"] == 0


def test_isolamento_e_visao_aluno(ctx):
    mid = ctx["mid"]
    tid = db.query_one("SELECT id FROM treinos WHERE data = '2026-11-18'")["id"]
    c2 = _login("t-prof2@t.com")
    tok2 = _csrf(c2, "/instrutor/alunos/novo")
    for url in (f"/instrutor/ciclos/{mid}/semanas", f"/instrutor/ciclos/{mid}/semanas/1",
                f"/instrutor/ciclos/{mid}/treinos/novo?modalidade=corrida", f"/instrutor/treinos/{tid}"):
        assert c2.get(url).status_code == 404, url
    for url in (f"/instrutor/treinos/{tid}", f"/instrutor/treinos/{tid}/excluir", f"/instrutor/treinos/{tid}/duplicar",
                f"/instrutor/ciclos/{mid}/semanas/1/copiar", f"/instrutor/ciclos/{mid}/treinos/novo?modalidade=corrida"):
        assert c2.post(url, data={"csrf": tok2, "data": "2026-11-20", "destino": "2"}).status_code == 404, url
    assert db.query_one("SELECT id FROM treinos WHERE id = ?", (tid,))

    a1 = _login("t-aluno1@t.com")
    pag = a1.get(f"/aluno/ciclos/{mid}/semanas/1").text
    assert "Tiros</b> 6× 400 m" in pag and "Agachamento" in pag
    assert "+ Corrida" not in pag and "Editar" not in pag and "Copiar esta semana" not in pag
    assert a1.get(f"/aluno/ciclos/{mid}/semanas").status_code == 302
    assert a1.get("/aluno/semana").status_code == 302
    assert a1.get(f"/instrutor/ciclos/{mid}/semanas/1").status_code == 403
    a2 = _login("t-aluno2@t.com")
    assert a2.get(f"/aluno/ciclos/{mid}/semanas/1").status_code == 404
    assert a2.get("/aluno/semana").headers["Location"].endswith("/aluno")   # sem macrociclo


def test_excluir_macro_apaga_treinos(ctx):
    c, tok = ctx["c"], ctx["tok"]
    a1 = ctx["a1"]
    r = c.post(f"/instrutor/alunos/{a1}/ciclos/novo", data={"csrf": tok, "nome": "Descartável",
                                                             "data_inicio": "2026-11-16", "modelo_corrida": "1"})
    mid2 = int(r.headers["Location"].rsplit("/", 1)[1])
    _post_corrida({**ctx, "mid": mid2}, "2026-11-17", [{"tipo": "Rodagem", "repeticoes": 1, "distancia": "6"}])
    tid = db.query_one("SELECT id FROM treinos WHERE macrociclo_id = ?", (mid2,))["id"]
    c.post(f"/instrutor/ciclos/{mid2}/excluir", data={"csrf": tok})
    assert db.query_one("SELECT COUNT(*) AS n FROM treinos WHERE macrociclo_id = ?", (mid2,))["n"] == 0
    assert db.query_one("SELECT COUNT(*) AS n FROM treino_corrida WHERE treino_id = ?", (tid,))["n"] == 0


# ------------------------------------------------------------- tempo, pace e volume
@pytest.mark.parametrize("txt,seg", [("72 s", 72), ("20 min", 1200), ("1 min 30", 90), ("1'30", 90), ("1:12", 72),
                                     ("1:05:00", 3900), ("1h10", 4200), ("45", 2700), ("1,5 min", 90), ("90 seg", 90),
                                     ("1 min forte / 1 min leve", None), ("", None), ("3x400", None)])
def test_ler_duracao(txt, seg):
    assert treinos.ler_duracao(txt) == seg


def test_pace_e_tempo_do_bloco():
    assert treinos.ler_pace("5:10/km") == 310 and treinos.ler_pace("5'10") == 310
    assert treinos.ler_pace("1:12") is None                      # rápido demais para ser /km
    assert treinos.fmt_pace(180) == "3:00/km"
    tb = treinos.tempo_bloco
    assert tb({"duracao": "20 min"}) == 1200
    assert tb({"distancia_m": 8000, "pace": "5:00"}) == 2400
    assert tb({"distancia_m": 400, "pace": "72 s"}) == 72         # tempo da repetição
    assert tb({"distancia_m": 400, "pace": "1:12"}) == 72
    assert tb({"distancia_m": 400, "pace": "72 s/km"}) is None
    assert tb({"distancia_m": 2000}) is None and tb({"pace": "5:00"}) is None


def test_volume_corrida():
    v = treinos.volume("corrida", [
        {"repeticoes": 1, "duracao": "15 min"},
        {"repeticoes": 8, "distancia_m": 400, "pace": "72 s"},
        {"repeticoes": 1, "distancia_m": 8000, "pace": "5:00/km"},
    ])
    assert v == {"metros": 11200, "segundos": 900 + 576 + 2400, "completo": True}
    v = treinos.volume("corrida", [{"repeticoes": 1, "distancia_m": 2000}])
    assert v["metros"] == 2000 and v["segundos"] == 0 and not v["completo"]


def test_volume_academia():
    v = treinos.volume("academia", [
        {"series": 4, "repeticoes": "8–10", "carga": "60 kg"},   # 4 × 9 × 60 = 2160
        {"series": 3, "repeticoes": "10", "carga": "22,5"},      # 3 × 10 × 22,5 = 675
    ])
    assert v == {"series": 7, "reps": 66, "kg": 2835, "completo": True}
    v = treinos.volume("academia", [{"series": 3, "repeticoes": "40 s", "carga": None},
                                    {"series": 2, "repeticoes": "12", "carga": "70% 1RM"}])
    assert v["series"] == 5 and v["reps"] == 24 and v["kg"] == 0 and not v["completo"]


def test_fmt():
    assert [treinos.fmt_duracao(x) for x in (72, 90, 600, 2076, 3900)] == ["1 min 12", "1 min 30", "10 min", "34 min", "1h05"]
    assert treinos.fmt_km(31200) == "31,2 km" and treinos.fmt_km(8000) == "8 km" and treinos.fmt_kg(10260) == "10.260 kg"


def test_totais_no_macrociclo_e_semana(ctx):
    c, mid = ctx["c"], ctx["mid"]
    pag = c.get(f"/instrutor/ciclos/{mid}").text
    assert "Total planejado no macrociclo" in pag and "Planejado" in pag and "km/sem." in pag
    sem = c.get(f"/instrutor/ciclos/{mid}/semanas/1").text
    assert "Volume da semana" in sem and 'title="Volume da sessão"' in sem
    assert "Total planejado no macrociclo" in _login("t-aluno1@t.com").get(f"/aluno/ciclos/{mid}").text
