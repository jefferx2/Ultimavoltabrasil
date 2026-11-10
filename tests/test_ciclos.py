import re
from datetime import date, timedelta

import pytest
from werkzeug.security import generate_password_hash

import ciclos
import db
from app import app, _macro_vigente

app.config["TESTING"] = True
SENHA = "senha-forte-1"


def _csrf(client, url):
    return re.search(r'name="csrf" value="(\w+)"', client.get(url).text).group(1)


def _login(email):
    c = app.test_client()
    c.post("/login", data={"email": email, "senha": SENHA, "csrf": _csrf(c, "/login")})
    return c


def _criar(nome, email, perfil, instrutor_id=None):
    return db.insert("INSERT INTO usuarios (nome, email, senha_hash, perfil, instrutor_id) VALUES (?, ?, ?, ?, ?)",
                     (nome, email, generate_password_hash(SENHA), perfil, instrutor_id))


@pytest.fixture(scope="module")
def base():
    p1 = _criar("Prof C1", "c-prof1@t.com", "instrutor")
    p2 = _criar("Prof C2", "c-prof2@t.com", "instrutor")
    a1 = _criar("Aluno C1", "c-aluno1@t.com", "aluno", p1)
    a2 = _criar("Aluno C2", "c-aluno2@t.com", "aluno", p1)
    return {"p1": p1, "p2": p2, "a1": a1, "a2": a2}


def _novo_macro(c, aluno_id, **extra):
    tok = _csrf(c, f"/instrutor/alunos/{aluno_id}/ciclos/novo")
    dados = {"csrf": tok, "nome": "Temporada 2027", "competicao": "Paulista Master 800 m",
             "data_inicio": "2026-11-16", "data_competicao": "2027-04-10",
             "modelo_academia": "1", "modelo_corrida": "1"}
    dados.update(extra)
    return c.post(f"/instrutor/alunos/{aluno_id}/ciclos/novo", data={k: v for k, v in dados.items() if v is not None})


# ------------------------------------------------------------- lógica pura
def test_distribuir_soma_e_ordem():
    for total in range(4, 80):
        d = ciclos.distribuir(total, [35, 30, 20, 15])
        assert sum(d) == total and min(d) >= 1 and d == sorted(d, reverse=True)
    assert ciclos.distribuir(2, [35, 30, 20, 15]) == [1, 1, 1, 1]


@pytest.mark.parametrize("inicio,comp", [(date(2026, 11, 16), date(2027, 4, 10)),
                                          (date(2026, 1, 5), date(2026, 3, 1)),
                                          (date(2026, 6, 1), date(2026, 6, 26)),
                                          (date(2026, 1, 1), date(2027, 12, 1))])
def test_pico_cai_na_competicao(inicio, comp):
    for mod in ciclos.MODALIDADES:
        fases = ciclos.com_datas(ciclos.fases_modelo(mod, inicio, comp), inicio)
        assert len(fases) == 5 and fases[-1]["nome"] == "Transição"
        assert fases[3]["inicio"] <= comp <= fases[3]["fim"], (mod, inicio, comp)
        for a, b in zip(fases, fases[1:]):  # sem buracos nem sobreposição
            assert b["inicio"] == a["fim"] + timedelta(days=1)


def test_ciclo_curto_demais_gera_aviso():
    ini, comp = date(2026, 6, 3), date(2026, 6, 20)   # 3 semanas não comportam 4 fases antes da prova
    fases = [dict(f, modalidade="academia") for f in ciclos.fases_modelo("academia", ini, comp)]
    v = ciclos.montar({"data_inicio": ini.isoformat(), "data_competicao": comp.isoformat()}, fases)
    assert "academia" in v["avisos"] and "corrida" not in v["avisos"]


def test_modelo_academia_igual_ao_slide():
    f = ciclos.fases_modelo("academia", date(2026, 1, 5), date(2026, 6, 1))
    assert [x["nome"] for x in f] == ["Endurance-Hipertrofia", "Hipertrofia", "Potência",
                                      "Pico de Força e Potência", "Transição"]
    assert [(x["series"], x["repeticoes"]) for x in f] == [("3–5", "15–20"), ("3–5", "8–10"), ("3–5", "4–6"),
                                                           ("1–3", "1–3"), ("1–2", "8–10")]
    assert [x["intensidade"] for x in f] == [2, 3, 4, 5, 3]   # baixa, moderada, alta, muito alta, moderada
    assert [x["volume"] for x in f] == [5, 4, 3, 2, 2]        # muito elevado, elevado, moderado, baixo, baixo


def test_fase_atual_e_semana():
    ini = date(2026, 1, 5)
    fases = ciclos.com_datas(ciclos.fases_modelo("corrida", ini, date(2026, 4, 26)), ini)
    a = ciclos.fase_atual(fases, ini + timedelta(days=8))
    assert a["fase"]["ordem"] == 1 and a["semana"] == 2
    assert ciclos.fase_atual(fases, ini - timedelta(days=1)) is None


# ------------------------------------------------------------- telas e regras
def test_criar_macro_com_modelo(base):
    c = _login("c-prof1@t.com")
    r = _novo_macro(c, base["a1"])
    assert r.status_code == 302
    mid = int(r.headers["Location"].rsplit("/", 1)[1])
    fases = db.query_all("SELECT * FROM fases WHERE macrociclo_id = ? ORDER BY modalidade, ordem", (mid,))
    assert len(fases) == 10
    assert {f["modalidade"] for f in fases} == {"academia", "corrida"}
    pag = c.get(f"/instrutor/ciclos/{mid}").text
    for trecho in ("Temporada 2027", "Linha do tempo", "<svg", "Endurance-Hipertrofia", "Base Aeróbica",
                   "Séries por exercício", "15–20", "Muito elevado", "🏁 competição"):
        assert trecho in pag, trecho
    assert "não cai na fase" not in pag          # pico alinhado: sem aviso
    assert "Temporada 2027" in c.get(f"/instrutor/alunos/{base['a1']}").text  # aparece na ficha


def test_criar_macro_sem_modelo_e_sem_competicao(base):
    c = _login("c-prof1@t.com")
    r = _novo_macro(c, base["a2"], nome="Base livre", data_competicao="", competicao="",
                    modelo_academia=None, modelo_corrida=None)
    mid = int(r.headers["Location"].rsplit("/", 1)[1])
    assert db.query_one("SELECT COUNT(*) AS n FROM fases WHERE macrociclo_id = ?", (mid,))["n"] == 0
    pag = c.get(f"/instrutor/ciclos/{mid}").text
    assert "Nenhuma fase de academia" in pag and "Nenhuma fase de corrida" in pag


def test_validacoes_macro(base):
    c = _login("c-prof1@t.com")
    r = _novo_macro(c, base["a1"], nome="", data_competicao="2026-11-01")
    assert "Informe o nome" in r.text and "depois da data de início" in r.text
    r = _novo_macro(c, base["a1"], data_inicio="", data_competicao="")
    assert "Data de início obrigatória" in r.text
    r = _novo_macro(c, base["a1"], data_inicio="2026-01-01", data_competicao="2029-01-01")
    assert "no máximo 2 anos" in r.text


def test_editar_fase_mover_excluir_e_aviso(base):
    c = _login("c-prof1@t.com")
    mid = int(_novo_macro(c, base["a1"], nome="Para editar").headers["Location"].rsplit("/", 1)[1])
    acad = db.query_all("SELECT * FROM fases WHERE macrociclo_id = ? AND modalidade = 'academia' ORDER BY ordem", (mid,))
    f1 = acad[0]
    tok = _csrf(c, f"/instrutor/fases/{f1['id']}")

    # validação
    r = c.post(f"/instrutor/fases/{f1['id']}", data={"csrf": tok, "nome": "", "semanas": "0", "intensidade": "9", "volume": "x"})
    assert "Informe o nome" in r.text and "Semanas" in r.text and "Intensidade" in r.text and "Volume" in r.text

    # edição: alonga a fase 1 em 5 semanas -> pico passa da competição -> aviso
    r = c.post(f"/instrutor/fases/{f1['id']}", data={
        "csrf": tok, "nome": "Adaptação", "objetivo": "Base", "semanas": str(f1["semanas"] + 5),
        "intensidade": "1", "volume": "5", "series": "2–3", "repeticoes": "15", "intensidade_ref": "40–50% 1RM",
        "volume_ref": "", "conteudo": "Circuito"})
    assert r.status_code == 302 and r.headers["Location"].endswith("#academia")
    f = db.query_one("SELECT * FROM fases WHERE id = ?", (f1["id"],))
    assert f["nome"] == "Adaptação" and f["intensidade"] == 1 and f["intensidade_ref"] == "40–50% 1RM" and f["volume_ref"] is None
    pag = c.get(f"/instrutor/ciclos/{mid}").text
    assert "não cai na fase" in pag and "40–50% 1RM" in pag and "Circuito" in pag

    # mover a fase 1 para depois
    c.post(f"/instrutor/fases/{f1['id']}/mover", data={"csrf": tok, "direcao": "abaixo"})
    ordem = [x["id"] for x in db.query_all("SELECT id FROM fases WHERE macrociclo_id = ? AND modalidade = 'academia' ORDER BY ordem", (mid,))]
    assert ordem[:2] == [acad[1]["id"], f1["id"]]
    # mover a primeira "acima" não faz nada
    c.post(f"/instrutor/fases/{acad[1]['id']}/mover", data={"csrf": tok, "direcao": "acima"})
    assert [x["id"] for x in db.query_all("SELECT id FROM fases WHERE macrociclo_id = ? AND modalidade = 'academia' ORDER BY ordem", (mid,))] == ordem

    # excluir renumera
    c.post(f"/instrutor/fases/{f1['id']}/excluir", data={"csrf": tok})
    ords = [x["ordem"] for x in db.query_all("SELECT ordem FROM fases WHERE macrociclo_id = ? AND modalidade = 'academia' ORDER BY ordem", (mid,))]
    assert ords == [1, 2, 3, 4]

    # nova fase de corrida entra no fim
    tok = _csrf(c, f"/instrutor/ciclos/{mid}/fases/nova?modalidade=corrida")
    r = c.post(f"/instrutor/ciclos/{mid}/fases/nova", data={"csrf": tok, "modalidade": "corrida", "nome": "Extra",
                                                            "semanas": "2", "intensidade": "2", "volume": "1"})
    assert r.status_code == 302
    extra = db.query_one("SELECT * FROM fases WHERE macrociclo_id = ? AND nome = 'Extra'", (mid,))
    assert extra["ordem"] == 6 and extra["modalidade"] == "corrida"
    assert c.get(f"/instrutor/ciclos/{mid}/fases/nova?modalidade=natacao").status_code == 404


def test_editar_e_excluir_macro(base):
    c = _login("c-prof1@t.com")
    mid = int(_novo_macro(c, base["a2"], nome="Apagar").headers["Location"].rsplit("/", 1)[1])
    tok = _csrf(c, f"/instrutor/ciclos/{mid}/editar")
    r = c.post(f"/instrutor/ciclos/{mid}/editar", data={"csrf": tok, "nome": "Renomeado", "data_inicio": "2026-11-16",
                                                         "data_competicao": "2027-04-10", "competicao": "", "observacoes": "obs"})
    assert r.status_code == 302
    assert db.query_one("SELECT nome, competicao, observacoes FROM macrociclos WHERE id = ?", (mid,)) == \
        {"nome": "Renomeado", "competicao": None, "observacoes": "obs"}
    r = c.post(f"/instrutor/ciclos/{mid}/excluir", data={"csrf": tok})
    assert r.headers["Location"].endswith(f"/instrutor/alunos/{base['a2']}")
    assert db.query_one("SELECT id FROM macrociclos WHERE id = ?", (mid,)) is None
    assert db.query_one("SELECT COUNT(*) AS n FROM fases WHERE macrociclo_id = ?", (mid,))["n"] == 0


def test_isolamento(base):
    c1 = _login("c-prof1@t.com")
    mid = int(_novo_macro(c1, base["a1"], nome="Privado").headers["Location"].rsplit("/", 1)[1])
    fid = db.query_one("SELECT id FROM fases WHERE macrociclo_id = ? LIMIT 1", (mid,))["id"]

    c2 = _login("c-prof2@t.com")
    tok = _csrf(c2, "/instrutor/alunos/novo")
    for url in (f"/instrutor/ciclos/{mid}", f"/instrutor/ciclos/{mid}/editar", f"/instrutor/fases/{fid}",
                f"/instrutor/alunos/{base['a1']}/ciclos/novo", f"/instrutor/ciclos/{mid}/fases/nova?modalidade=corrida"):
        assert c2.get(url).status_code == 404, url
    for url in (f"/instrutor/ciclos/{mid}/excluir", f"/instrutor/fases/{fid}/excluir", f"/instrutor/fases/{fid}/mover"):
        assert c2.post(url, data={"csrf": tok}).status_code == 404, url
    assert db.query_one("SELECT id FROM macrociclos WHERE id = ?", (mid,))  # nada foi apagado

    a1 = _login("c-aluno1@t.com")
    assert a1.get(f"/instrutor/ciclos/{mid}").status_code == 403
    assert a1.get(f"/aluno/ciclos/{mid}").status_code == 200
    a2 = _login("c-aluno2@t.com")
    assert a2.get(f"/aluno/ciclos/{mid}").status_code == 404


def test_visao_do_aluno(base):
    a = _login("c-aluno1@t.com")
    pag = a.get("/aluno").text
    assert "Linha do tempo" in pag and "<svg" in pag
    assert "Editar" not in pag and "+ Fase" not in pag      # somente leitura
    assert "Outros macrociclos" in pag

    sem = _criar("Sem ciclo", "c-sem@t.com", "aluno", base["p1"])
    assert "ainda não montou" in _login("c-sem@t.com").get("/aluno").text


def test_macro_vigente(base):
    aid = _criar("Vigente", "c-vig@t.com", "aluno", base["p1"])
    hoje = date(2027, 2, 1)
    for nome, ini in (("Passado", "2025-01-06"), ("Atual", "2026-12-07"), ("Futuro", "2027-08-02")):
        mid = db.insert("INSERT INTO macrociclos (aluno_id, nome, data_inicio) VALUES (?, ?, ?)", (aid, nome, ini))
        with db.Transacao() as t:
            for f in ciclos.fases_modelo("corrida", date.fromisoformat(ini), date.fromisoformat(ini) + timedelta(weeks=15)):
                t.insert("INSERT INTO fases (macrociclo_id, modalidade, ordem, nome, semanas, intensidade, volume) "
                         "VALUES (?, 'corrida', ?, ?, ?, ?, ?)", (mid, f["ordem"], f["nome"], f["semanas"], f["intensidade"], f["volume"]))
    assert _macro_vigente(aid, hoje)[0][0]["nome"] == "Atual"
    assert _macro_vigente(aid, date(2027, 6, 1))[0][0]["nome"] == "Futuro"
    assert _macro_vigente(aid, date(2028, 6, 1))[0][0]["nome"] == "Futuro"   # o mais recente
    assert _macro_vigente(aid, date(2024, 6, 1))[0][0]["nome"] == "Passado"  # o próximo a começar


def test_painel_instrutor_conta_macros(base):
    pag = _login("c-prof1@t.com").get("/instrutor").text
    n = db.query_one("SELECT COUNT(*) AS n FROM macrociclos m JOIN usuarios u ON u.id = m.aluno_id "
                     "WHERE u.instrutor_id = ? AND u.ativo = 1", (base["p1"],))["n"]
    assert n >= 2 and f'<span class="numero">{n}</span> <span class="tag">macrociclos</span>' in pag


def test_curva_nao_ultrapassa_os_niveis():
    """A curva suavizada não pode passar acima/abaixo dos valores das fases (sem 'barrigas')."""
    import itertools
    for niveis in itertools.product([1, 3, 5], repeat=4):
        fases = ciclos.com_datas([{"ordem": i + 1, "nome": str(i), "semanas": s, "intensidade": n, "volume": 6 - n}
                                  for i, (n, s) in enumerate(zip(niveis, (5, 1, 3, 2)))], date(2026, 1, 5))
        g = ciclos.grafico(fases, 11)
        for chave in ("volume", "intensidade"):
            ys = [float(v) for v in re.findall(r"[\d.]+,([\d.]+)", g[chave])]
            pts = [y for _, y in g["pontos"][chave]]
            assert min(pts) - 0.05 <= min(ys) and max(ys) <= max(pts) + 0.05, (niveis, chave)


# ------------------------------------------------------------- metodologia × planejado
def test_intensidade_planejada_academia_segue_a_tabela():
    m = {1: {"series": 10, "reps_x_series": 175, "series_com_reps": 10},   # 17,5 reps -> 2 (baixa)
         2: {"series": 10, "reps_x_series": 90, "series_com_reps": 10},    # 9 reps    -> 3 (moderada)
         3: {"series": 10, "reps_x_series": 50, "series_com_reps": 10},    # 5 reps    -> 4 (alta)
         4: {"series": 10, "reps_x_series": 20, "series_com_reps": 10},    # 2 reps    -> 5 (muito alta)
         5: {"series": 4, "reps_x_series": 0, "series_com_reps": 0}}       # sem reps numéricas: sem intensidade
    n = ciclos.niveis_planejados(m, "academia", referencia=20)
    assert [round(n["intensidade"][w], 2) for w in (1, 2, 3, 4)] == [2, 3, 4, 5] and 5 not in n["intensidade"]
    assert n["volume"][1] == 2.5 and n["volume"][5] == 1 and not n["relativa"]


def test_intensidade_planejada_corrida_por_qualidade_e_volume_relativo():
    m = {1: {"metros": 30000, "segundos": 10000, "segundos_qualidade": 0},
         2: {"metros": 60000, "segundos": 10000, "segundos_qualidade": 2000},   # 20% -> 3
         3: {"metros": 45000, "segundos": 10000, "segundos_qualidade": 5000}}   # 50% -> 5 (teto)
    n = ciclos.niveis_planejados(m, "corrida")                                  # sem referência: relativa
    assert n["relativa"] and n["referencia"] == 60 and n["volume"] == {1: 2.5, 2: 5.0, 3: 3.75}
    assert [n["intensidade"][w] for w in (1, 2, 3)] == [1.5, 3, 5]
    assert ciclos.niveis_planejados(m, "corrida", referencia=40)["volume"][2] == 7.5   # passa de 5


def test_excessos_por_fase():
    ini = date(2026, 1, 5)
    fases = ciclos.com_datas(ciclos.fases_modelo("corrida", ini, date(2026, 4, 26)), ini)  # base: vol 5, int 2
    plan = {"volume": {1: 5.4, 2: 5.6, 3: 3.0}, "intensidade": {1: 2.4, 2: 3.0}}
    acima = ciclos.excessos(fases, plan)
    assert acima == {"volume": {2}, "intensidade": {2}}          # 5,4 está dentro da tolerância (0,5)
    assert fases[0]["acima"] == {"volume": 1, "intensidade": 1} and fases[1]["acima"] == {"volume": 0, "intensidade": 0}


def test_grafico_com_planejado_e_eixo_que_cresce():
    ini = date(2026, 1, 5)
    fases = ciclos.com_datas(ciclos.fases_modelo("corrida", ini, date(2026, 4, 26)), ini)
    g = ciclos.grafico(fases, 18, ini, {"volume": {1: 4, 2: 6.3, 4: 5}, "intensidade": {}}, {"volume": {2}, "intensidade": set()})
    assert g["ymax"] == 7
    assert g["plan_path"]["volume"].count("M") == 2               # semana 3 sem treino interrompe a linha
    assert [p["acima"] for p in g["plan_pts"]["volume"]] == [False, True, False]
    assert g["meses"][0]["rotulo"] == "fev" and any(m["rotulo"] == "abr" for m in g["meses"])


def test_referencia_no_macro_e_alerta_na_tela(base):
    c = _login("c-prof1@t.com")
    r = _novo_macro(c, base["a2"], nome="Com referência", ref_km_semana="abc", ref_series_semana="-3")
    assert "Referência de km/semana" in r.text and "Referência de séries/semana" in r.text
    r = _novo_macro(c, base["a2"], nome="Com referência", data_inicio="2026-11-16", data_competicao="2027-04-10",
                    ref_km_semana="40", ref_series_semana="60")
    mid = int(r.headers["Location"].rsplit("/", 1)[1])
    assert db.query_one("SELECT ref_km_semana, ref_series_semana FROM macrociclos WHERE id = ?", (mid,)) == \
        {"ref_km_semana": 40.0, "ref_series_semana": 60}
    # semana 1 (Base Aeróbica: volume 5, intensidade 2) com 60 km, metade em tiros -> volume 7,5 e intensidade 5
    with db.Transacao() as t:
        tid = t.insert("INSERT INTO treinos (macrociclo_id, data, modalidade) VALUES (?, '2026-11-17', 'corrida')", (mid,))
        t.insert("INSERT INTO treino_corrida (treino_id, ordem, tipo, repeticoes, distancia_m, pace) VALUES (?, 1, 'Rodagem', 1, 30000, '5:00')", (tid,))
        t.insert("INSERT INTO treino_corrida (treino_id, ordem, tipo, repeticoes, distancia_m, pace) VALUES (?, 2, 'Tiros', 30, 1000, '5:00')", (tid,))
    pag = c.get(f"/instrutor/ciclos/{mid}").text
    assert "Volume 5 = 40 km/semana" in pag and "ACIMA da metodologia" in pag
    assert "▲ volume acima em 1 sem." in pag and "▲ intensidade acima em 1 sem." in pag
    assert 'data-alterna="plan-vol"' in pag and 'data-camada="met-int"' in pag
    assert 'value="40"' in c.get(f"/instrutor/ciclos/{mid}/editar").text

    # sem referência: escala relativa e aviso para definir
    mid2 = int(_novo_macro(c, base["a2"], nome="Sem ref").headers["Location"].rsplit("/", 1)[1])
    with db.Transacao() as t:
        tid = t.insert("INSERT INTO treinos (macrociclo_id, data, modalidade) VALUES (?, '2026-11-17', 'corrida')", (mid2,))
        t.insert("INSERT INTO treino_corrida (treino_id, ordem, tipo, repeticoes, distancia_m) VALUES (?, 1, 'Rodagem', 1, 10000)", (tid,))
    pag = c.get(f"/instrutor/ciclos/{mid2}").text
    assert "Escala relativa: volume 5 = maior semana planejada (10 km)" in pag and "Defina a referência" in pag
    assert "Defina a referência" not in _login("c-aluno2@t.com").get(f"/aluno/ciclos/{mid2}").text
