"""Registro do treino pelo aluno e acompanhamento pelo professor."""
from datetime import date, timedelta

from flask import abort, flash, redirect, render_template, request, url_for

import ciclos
import daniels
import db
import registros
import treinos
from app import _aluno_do_instrutor, _aluno_por_id, _macro_vigente, app, login_obrigatorio, perfil_corrida


def _treino_do_aluno(treino_id, aluno_id):
    t = db.query_one("SELECT t.id FROM treinos t JOIN macrociclos m ON m.id = t.macrociclo_id "
                     "WHERE t.id = ? AND m.aluno_id = ?", (treino_id, aluno_id))
    if not t:
        abort(404)
    return treinos.um(treino_id)


def _contexto_registro(treino, aluno, reg):
    perfil = perfil_corrida(aluno)
    ultimas = registros.ultimas_cargas(aluno["id"], treino["data"]) if treino["modalidade"] == "academia" else {}
    macro = db.query_one("SELECT * FROM macrociclos WHERE id = ?", (treino["macrociclo_id"],))
    ini = date.fromisoformat(macro["data_inicio"])
    salvo = reg if reg and "form" not in reg else None   # com erro de validação, reg é só o formulário digitado
    return {"treino": treino, "reg": reg, "perfil": perfil, "ultimas": ultimas, "macro": macro, "aluno": aluno,
            "semana_n": treinos.semana_de(ini, date.fromisoformat(treino["data"])),
            "comparacao": registros.comparar_blocos(treino, salvo, perfil["paces"]),
            "real": registros.realizado(treino, salvo) if salvo else None,
            "vol": treinos.volume(treino["modalidade"], treino["itens"]),
            "STATUS": registros.STATUS, "ESFORCO": registros.ESFORCO, "d": daniels,
            "fmt_dist": treinos.fmt_distancia, "dia_nome": treinos.DIAS[date.fromisoformat(treino["data"]).weekday()]}


# ---------------------------------------------------------------- aluno: registrar o treino
@app.route("/aluno/treinos/<int:treino_id>/registro", methods=["GET", "POST"])
@login_obrigatorio("aluno")
def registro_treino(user, treino_id):
    treino = _treino_do_aluno(treino_id, user["id"])
    aluno = _aluno_por_id(user["id"])
    if date.fromisoformat(treino["data"]) > date.today():
        flash("Esse treino ainda não aconteceu: registre a partir do dia dele.", "erro")
        return redirect(url_for("aluno_semana_atual"))
    reg = registros.carregar([treino_id]).get(treino_id)
    if request.method == "POST":
        dados, linhas, erros = registros.ler_form(request.form, treino)
        if not erros:
            registros.salvar(treino, dados, linhas)
            flash("Treino registrado. Bom trabalho!" if dados["status"] != "nao_feito" else "Registro salvo.", "ok")
            ctx = _contexto_registro(treino, aluno, None)
            return redirect(url_for("aluno_semana", macro_id=treino["macrociclo_id"], n=ctx["semana_n"]) + f"#d{treino['data']}")
        for e in erros:
            flash(e, "erro")
        reg = {"form": request.form}  # devolve o que foi digitado
    return render_template("registro.html", editavel=True, **_contexto_registro(treino, aluno, reg))


# ---------------------------------------------------------------- professor: ver o registro
@app.route("/instrutor/treinos/<int:treino_id>/registro")
@login_obrigatorio("instrutor")
def registro_ver(user, treino_id):
    t = db.query_one("SELECT t.id, m.aluno_id FROM treinos t JOIN macrociclos m ON m.id = t.macrociclo_id "
                     "JOIN usuarios u ON u.id = m.aluno_id WHERE t.id = ? AND u.instrutor_id = ?", (treino_id, user["id"]))
    if not t:
        abort(404)
    treino = treinos.um(treino_id)
    reg = registros.carregar([treino_id]).get(treino_id)
    return render_template("registro.html", editavel=False, **_contexto_registro(treino, _aluno_por_id(t["aluno_id"]), reg))


# ---------------------------------------------------------------- acompanhamento
def _alertas(r7, semanas):
    alertas = []
    if r7["planejadas"] and not r7["registradas"]:
        alertas.append("Sem registros nos últimos 7 dias")
    if r7["adesao"] is not None and r7["planejadas"] >= 3 and r7["adesao"] < 50:
        alertas.append(f"Adesão baixa ({r7['adesao']}%)")
    if r7["rpe_medio"] and r7["rpe_medio"] >= 8.5:
        alertas.append(f"Esforço médio alto ({r7['rpe_medio']:g})".replace(".", ","))
    anteriores = [s["carga_interna"] for s in semanas[-4:-1] if s["carga_interna"]]
    atual = semanas[-1]["carga_interna"]
    if anteriores and atual > 1.5 * (sum(anteriores) / len(anteriores)):
        alertas.append("Carga da semana mais de 50% acima da média das 3 anteriores")
    return alertas


@app.route("/instrutor/acompanhamento")
@login_obrigatorio("instrutor")
def acompanhamento(user):
    alunos = db.query_all("SELECT * FROM usuarios WHERE instrutor_id = ? AND perfil = 'aluno' AND ativo = 1 ORDER BY nome",
                          (user["id"],))
    hoje = date.today()
    todas = registros.sessoes([a["id"] for a in alunos], hoje - timedelta(weeks=8), hoje + timedelta(days=6))
    linhas = []
    for a in alunos:
        dele = [t for t in todas if t["aluno_id"] == a["id"]]
        r7 = registros.resumo([t for t in dele if t["data"] >= (hoje - timedelta(days=6)).isoformat()], hoje)
        sem = registros.semanas_calendario(dele, 4, hoje)
        linhas.append({"aluno": a, "r7": r7, "alertas": _alertas(r7, sem), "tem_treino": bool(dele),
                       "proximo": next((t for t in dele if t["data"] > hoje.isoformat()), None)})
    linhas.sort(key=lambda l: (not l["alertas"], l["aluno"]["nome"]))
    return render_template("acompanhamento.html", linhas=linhas, MODALIDADES=ciclos.MODALIDADES)


def _pagina_aluno(aluno, editavel):
    hoje = date.today()
    lista = registros.sessoes([aluno["id"]], hoje - timedelta(weeks=12), hoje + timedelta(days=6))
    semanas = registros.semanas_calendario(lista, 8, hoje)
    perfil = perfil_corrida(aluno)
    sessoes = [t for t in reversed(lista) if t["data"] <= hoje.isoformat()][:30]
    for t in sessoes:
        t["comparacao"] = registros.comparar_blocos(t, t["registro"], perfil["paces"])
    progressao = registros.progressao_cargas(aluno["id"])
    for e in progressao:
        e["linha"] = registros.sparkline([p["max"] for p in e["pontos"]])
    maior_km = max([max(s["km_plan"], s["km_real"]) for s in semanas] + [1])
    (macro, _), _ = _macro_vigente(aluno["id"])
    r7 = registros.resumo([t for t in lista if t["data"] >= (hoje - timedelta(days=6)).isoformat()], hoje)
    return render_template("acompanhamento_aluno.html", aluno=aluno, semanas=semanas, sessoes=sessoes,
                           progressao=progressao, perfil=perfil, maior_km=maior_km, editavel=editavel,
                           r7=r7, alertas=_alertas(r7, semanas), macro=macro, STATUS=registros.STATUS,
                           fmt_dist=treinos.fmt_distancia, d=daniels)


@app.route("/instrutor/alunos/<int:aluno_id>/acompanhamento")
@login_obrigatorio("instrutor")
def acompanhamento_aluno(user, aluno_id):
    return _pagina_aluno(_aluno_do_instrutor(aluno_id, user["id"]), editavel=True)


@app.route("/aluno/acompanhamento")
@login_obrigatorio("aluno")
def aluno_acompanhamento(user):
    return _pagina_aluno(_aluno_por_id(user["id"]), editavel=False)


# ---------------------------------------------------------------- filtros usados nessas telas
app.add_template_filter(lambda t: treinos.ler_pace(t), "pace_s")


@app.template_filter("primeiro_num")
def _primeiro_num(texto):
    import re
    m = re.search(r"\d+", texto or "")
    return m.group() if m else ""


@app.context_processor
def _hoje():
    return {"hoje_iso": lambda: date.today().isoformat()}
