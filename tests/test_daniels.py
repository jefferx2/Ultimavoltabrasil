"""Metodologia Jack Daniels: VDOT, paces, zonas, limites e integração com as telas."""
import re
from datetime import date, timedelta

import pytest
from werkzeug.security import generate_password_hash

import daniels as d
import db
import treinos
from app import app

app.config["TESTING"] = True
SENHA = "senha-forte-1"


def mmss(seg):
    return f"{int(seg // 60)}:{round(seg % 60):02d}"


# ------------------------------------------------------------- fórmulas x livro
def test_vdot_de_provas_conhecidas():
    assert round(d.vdot(5000, 19 * 60 + 57), 1) == 50.0          # tabela: 5 km 19:57 = VDOT 50
    assert round(d.vdot(1609, 5 * 60 + 44)) == 51                # livro: milha 5:44 = VDOT 51
    assert round(d.vdot(42195, 3 * 3600 + 10 * 60 + 49)) == 50   # maratona 3:10:49 = VDOT 50


@pytest.mark.parametrize("v,dist,esperado", [(40, 5000, 24 * 60 + 8), (50, 5000, 19 * 60 + 57), (50, 10000, 41 * 60 + 21),
                                             (50, 21097, 3600 + 31 * 60 + 35), (55, 5000, 18 * 60 + 22),
                                             (50, 42195, 3 * 3600 + 10 * 60 + 49)])
def test_previsao_de_prova_bate_com_a_tabela(v, dist, esperado):
    assert abs(d.prever_tempo(v, dist) - esperado) <= max(3, esperado * 0.002)


def test_paces_vdot_51_iguais_ao_livro():
    p = d.paces(51)   # livro: E 4:52–5:29 · M 4:27 · T 4:11 · I 3:51 /km · R 86 s/400
    assert [mmss(x) for x in p["E_faixa"]] == ["4:52", "5:29"]
    assert mmss(p["M"]) == "4:27" and mmss(p["T"]) == "4:11" and mmss(p["I"]) == "3:51"
    assert d.tempo_rep(p["R"], 400) == "1:26" and d.tempo_rep(p["I"], 400) == "1:32" and d.tempo_rep(p["T"], 400) == "1:40"


def test_zona_do_pace():
    p = d.paces(51)
    assert [d.zona_do_pace(x, p) for x in (330, 300, 268, 252, 232, 214, 190)] == ["E", "E", "M", "T", "I", "R", "R"]


def test_limites_semanais():
    l = d.limites_semana(60, {"T": 6.0, "I": 4.9, "R": 3.5})
    assert l["T"]["ok"] and not l["I"]["ok"] and not l["R"]["ok"]          # 10% = 6 · 8% = 4,8 · 5% = 3
    assert d.limites_semana(150, {"I": 11, "R": 7.9})["I"]["limite_km"] == 10  # teto absoluto de I = 10 km
    assert d.limites_semana(200, {"R": 8.5})["R"]["limite_km"] == 8 and d.limites_semana(150, {})["R"]["limite_km"] == 7.5


def test_faixas():
    assert d.faixa("800", "media")["max"] == 64 and d.faixa("meia", "alta")["texto"] == "100 a 130 km/sem"
    assert d.faixa("800", None) is None and d.faixa("xyz", "alta") is None


# ------------------------------------------------------------- zonas dos blocos e métricas
def test_zona_do_bloco():
    p = d.paces(51)
    zb = treinos.zona_do_bloco
    assert zb({"zona": "T", "tipo": "Rodagem"}, p) == "T"                                    # escolhida vence
    assert zb({"tipo": "Rodagem", "distancia_m": 8000, "pace": "3:50/km"}, p) == "I"         # pelo pace
    assert zb({"tipo": "Tiros", "distancia_m": 400, "pace": "86 s"}, p) == "R"               # tempo da repetição
    assert zb({"tipo": "Tiros", "distancia_m": 400, "duracao": "1:32"}, p) == "I"           # pela duração
    assert zb({"tipo": "Limiar", "distancia_m": 5000}, p) == "T" and zb({"tipo": "Longão"}) == "E"  # pelo tipo


def test_metricas_semanais_com_zonas_e_limites():
    p = d.paces(51)
    lista = [{"data": "2026-01-06", "modalidade": "corrida", "itens": [
        {"tipo": "Rodagem", "zona": "E", "repeticoes": 1, "distancia_m": 10000},
        {"tipo": "Intervalado", "zona": "I", "repeticoes": 6, "distancia_m": 1000},       # 6 km de I em 16 km
    ]}]
    m = treinos.metricas_semanais(lista, date(2026, 1, 5), p)["corrida"][1]
    assert m["metros"] == 16000 and m["zonas"]["I"]["metros"] == 6000
    assert abs(m["zonas"]["E"]["segundos"] - 10 * p["E"]) < 1 and abs(m["zonas"]["I"]["segundos"] - 6 * p["I"]) < 1
    assert m["fora_limite"] == ["I"]                                                        # 8% de 16 = 1,28 km
    pontos_min = m["pontos"] / (m["segundos"] / 60)
    assert 0.2 < pontos_min < 1.0


# ------------------------------------------------------------- telas
def _csrf(c, url):
    return re.search(r'name="csrf" value="(\w+)"', c.get(url).text).group(1)


def _login(email):
    c = app.test_client()
    c.post("/login", data={"email": email, "senha": SENHA, "csrf": _csrf(c, "/login")})
    return c


@pytest.fixture(scope="module")
def ctx():
    p1 = db.insert("INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES ('Prof D', 'd-prof@t.com', ?, 'instrutor')",
                   (generate_password_hash(SENHA),))
    db.insert("INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES ('Prof D2', 'd-prof2@t.com', ?, 'instrutor')",
              (generate_password_hash(SENHA),))
    a = db.insert("INSERT INTO usuarios (nome, email, senha_hash, perfil, instrutor_id) VALUES ('Bia Corredora', 'd-aluno@t.com', ?, 'aluno', ?)",
                  (generate_password_hash(SENHA), p1))
    c = _login("d-prof@t.com")
    return {"c": c, "a": a, "tok": _csrf(c, f"/instrutor/alunos/{a}")}


def test_anamnese_salva_e_mostra_faixa(ctx):
    c, a, tok = ctx["c"], ctx["a"], ctx["tok"]
    r = c.post(f"/instrutor/alunos/{a}", data={"csrf": tok, "nome": "Bia Corredora", "email": "d-aluno@t.com",
                                              "prova_categoria": "800", "nivel": "alta", "volume_atual_km": "55,5",
                                              "dias_semana": "9"})
    assert "Dias disponíveis" in r.text
    r = c.post(f"/instrutor/alunos/{a}", data={"csrf": tok, "nome": "Bia Corredora", "email": "d-aluno@t.com",
                                              "prova_categoria": "800", "nivel": "alta", "volume_atual_km": "55,5",
                                              "dias_semana": "5"})
    assert r.status_code == 302
    al = db.query_one("SELECT prova_categoria, nivel, volume_atual_km, dias_semana FROM usuarios WHERE id = ?", (a,))
    assert al == {"prova_categoria": "800", "nivel": "alta", "volume_atual_km": 55.5, "dias_semana": 5}
    pag = c.get(f"/instrutor/alunos/{a}").text
    assert "800 m · Alta (avançado / competitivo) → 80 a 96 km/sem" in pag and 'class="sel">80–96 km' in pag
    assert "Registre um tempo recente" in pag


def test_avaliacoes_vdot_e_paces(ctx):
    c, a, tok = ctx["c"], ctx["a"], ctx["tok"]
    url = f"/instrutor/alunos/{a}/avaliacoes"
    hoje = date.today()
    erros = c.post(url, data={"csrf": tok, "data": (hoje + timedelta(days=1)).isoformat(), "distancia": "5000", "tempo": "20:00"}, follow_redirects=True).text
    assert "não pode ser no futuro" in erros
    assert "Informe o tempo" in c.post(url, data={"csrf": tok, "data": hoje.isoformat(), "distancia": "5000", "tempo": "abc"}, follow_redirects=True).text
    assert "fora do esperado" in c.post(url, data={"csrf": tok, "data": hoje.isoformat(), "distancia": "5000", "tempo": "9:00"}, follow_redirects=True).text
    assert "Teste de 12 minutos" in c.post(url, data={"csrf": tok, "data": hoje.isoformat(), "distancia": "cooper", "distancia_cooper": ""}, follow_redirects=True).text
    assert db.query_one("SELECT COUNT(*) AS n FROM avaliacoes WHERE aluno_id = ?", (a,))["n"] == 0

    antiga = (hoje - timedelta(days=60)).isoformat()
    c.post(url, data={"csrf": tok, "data": antiga, "distancia": "cooper", "distancia_cooper": "2,8 km"})
    pag = c.post(url, data={"csrf": tok, "data": (hoje - timedelta(days=10)).isoformat(), "distancia": "milha",
                            "tempo": "5:44", "tipo": "prova", "descricao": "Pista"}, follow_redirects=True).text
    assert "VDOT 50,9" in pag or "VDOT 51,0" in pag
    esperado = d.paces(50.9)                                   # VDOT guardado com 1 casa
    assert d.fmt_pace(esperado["T"]) in pag and d.tempo_rep(esperado["R"], 400) in pag
    assert "em uso" in pag and "mais de 6 semanas" not in pag
    av = db.query_all("SELECT tipo, distancia_m, tempo_s FROM avaliacoes WHERE aluno_id = ? ORDER BY data", (a,))
    assert av[0] == {"tipo": "teste", "distancia_m": 2800, "tempo_s": 720}

    # outro professor não exclui; o dono exclui
    aid = db.query_one("SELECT id FROM avaliacoes WHERE aluno_id = ? AND distancia_m = 2800", (a,))["id"]
    c2 = _login("d-prof2@t.com")
    assert c2.post(f"/instrutor/avaliacoes/{aid}/excluir", data={"csrf": _csrf(c2, "/instrutor/alunos/novo")}).status_code == 404
    assert c2.post(f"/instrutor/alunos/{a}/avaliacoes", data={"csrf": _csrf(c2, "/instrutor/alunos/novo"), "data": hoje.isoformat(),
                                                             "distancia": "5000", "tempo": "20:00"}).status_code == 404
    c.post(f"/instrutor/avaliacoes/{aid}/excluir", data={"csrf": tok})
    assert db.query_one("SELECT COUNT(*) AS n FROM avaliacoes WHERE aluno_id = ?", (a,))["n"] == 1


def test_treino_com_zona_semana_e_grafico(ctx):
    c, a, tok = ctx["c"], ctx["a"], ctx["tok"]
    seg = date.today() - timedelta(days=date.today().weekday())
    r = c.post(f"/instrutor/alunos/{a}/ciclos/novo", data={"csrf": tok, "nome": "Temporada D", "data_inicio": seg.isoformat(),
                                                           "data_competicao": (seg + timedelta(weeks=16)).isoformat(),
                                                           "modelo_corrida": "1"})
    mid = int(r.headers["Location"].rsplit("/", 1)[1])
    form = c.get(f"/instrutor/ciclos/{mid}/treinos/novo?modalidade=corrida&data={seg.isoformat()}").text
    assert 'name="zona"' in form and "Paces de Bia" in form and '"I": 231' in form       # 3:51/km = 231 s

    dados = {"csrf": tok, "modalidade": "corrida", "data": seg.isoformat(), "titulo": "Intervalado", "observacoes": "",
             "item_id": ["", ""], "tipo": ["Rodagem", "Intervalado"], "zona": ["E", "I"], "repeticoes": ["1", "6"],
             "distancia": ["10", "1000"], "duracao": ["", ""], "pace": ["", "3:51/km"], "recuperacao": ["", "3 min"],
             "observacao": ["", ""]}
    assert c.post(f"/instrutor/ciclos/{mid}/treinos/novo", data=dados).status_code == 302
    assert [b["zona"] for b in db.query_all("SELECT zona FROM treino_corrida tc JOIN treinos t ON t.id = tc.treino_id "
                                            "WHERE t.macrociclo_id = ? ORDER BY tc.ordem", (mid,))] == ["E", "I"]
    sem = c.get(f"/instrutor/ciclos/{mid}/semanas/1").text
    assert "Corrida por zona (Daniels)" in sem and "Acima do limite semanal de Daniels em: <b>I</b>" in sem
    assert "(1:32/1000 m)" not in sem                                                   # só repetições < 1000 m
    macro = c.get(f"/instrutor/ciclos/{mid}").text
    assert "topo da faixa 800 m" in macro and "Volume 5 = 96 km/semana" in macro
    assert "limite T/I/R excedido em 1 sem." in macro and "pontos por minuto" in macro
    aluno = _login("d-aluno@t.com").get(f"/aluno/ciclos/{mid}/semanas/1").text
    assert "Corrida por zona (Daniels)" in aluno


def test_aluno_ve_os_proprios_paces(ctx):
    pag = _login("d-aluno@t.com").get("/aluno").text
    v = db.query_one("SELECT vdot FROM avaliacoes WHERE aluno_id = ? ORDER BY data DESC LIMIT 1", (ctx["a"],))["vdot"]
    assert "Seus ritmos de treino" in pag and d.fmt_pace(d.paces(v)["T"]) in pag
