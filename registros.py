"""Registro do treino pelo aluno (o que foi realizado) e cálculos do acompanhamento."""
import re
from datetime import date, timedelta

import daniels
import db
import treinos

STATUS = {"feito": "Feito", "parcial": "Feito em parte", "nao_feito": "Não feito"}
ESFORCO = {1: "Muito leve", 2: "Leve", 3: "Moderado", 4: "Um pouco difícil", 5: "Difícil", 6: "Difícil",
           7: "Muito difícil", 8: "Muito difícil", 9: "Quase máximo", 10: "Máximo"}


# ---------------------------------------------------------------- leitura de valores
def ler_tempos_reps(texto):
    """Tempos de cada repetição: '72 71 70', '1:12, 1:11', '72s;71s'. Número sem unidade = segundos.
    Devolve lista de segundos. Inválido -> ValueError."""
    t = (texto or "").strip().lower().replace(",", " ").replace(";", " ")
    if not t:
        return []
    saida = []
    for tok in t.split():
        if re.fullmatch(r"\d+(\.\d+)?s?", tok):
            v = float(tok.rstrip("s"))
        else:
            v = treinos.ler_duracao(tok)
        if not v or v <= 0 or v > 7200:
            raise ValueError(tok)
        saida.append(float(v))
    return saida


def ler_carga(texto):
    t = (texto or "").strip().lower().replace(" ", "").replace(",", ".").removesuffix("kg")
    if not t:
        return None
    v = float(t)
    if not 0 <= v <= 1000:
        raise ValueError(texto)
    return v


# ---------------------------------------------------------------- carregar
def carregar(treino_ids):
    """{treino_id: registro} com 'corrida' {item_id: linha} e 'series' {item_id: [linhas por série]}."""
    ids = list(treino_ids)
    if not ids:
        return {}
    marca = ",".join("?" * len(ids))
    regs = db.query_all(f"SELECT * FROM registros WHERE treino_id IN ({marca})", ids)
    if not regs:
        return {}
    rids = [r["id"] for r in regs]
    m2 = ",".join("?" * len(rids))
    corr = db.query_all(f"SELECT * FROM registro_corrida WHERE registro_id IN ({m2})", rids)
    ser = db.query_all(f"SELECT * FROM registro_series WHERE registro_id IN ({m2}) ORDER BY serie", rids)
    por_id = {}
    for r in regs:
        r["corrida"], r["series"] = {}, {}
        por_id[r["id"]] = r
    for c in corr:
        c["tempos"] = [float(x) for x in (c["tempos_reps"] or "").split(",") if x]
        por_id[c["registro_id"]]["corrida"][c["item_id"]] = c
    for s in ser:
        por_id[s["registro_id"]]["series"].setdefault(s["item_id"], []).append(s)
    return {r["treino_id"]: r for r in regs}


def ultimas_cargas(aluno_id, ate_data):
    """Última carga registrada de cada exercício (nome em minúsculas) antes da data: {nome: (kg, reps, data)}."""
    linhas = db.query_all(
        "SELECT a.exercicio, s.carga_kg, s.reps, t.data FROM registro_series s "
        "JOIN registros r ON r.id = s.registro_id JOIN treinos t ON t.id = r.treino_id "
        "JOIN treino_academia a ON a.id = s.item_id JOIN macrociclos m ON m.id = t.macrociclo_id "
        "WHERE m.aluno_id = ? AND t.data < ? AND s.carga_kg IS NOT NULL ORDER BY t.data, s.serie", (aluno_id, ate_data))
    ult = {}
    for l in linhas:  # vale o dia mais recente; no mesmo dia, a maior carga (empate: mais repetições)
        chave = l["exercicio"].strip().lower()
        atual = ult.get(chave)
        melhor = atual is not None and l["data"] == atual[2] and (
            l["carga_kg"] > atual[0] or (l["carga_kg"] == atual[0] and (l["reps"] or 0) > (atual[1] or 0)))
        if atual is None or l["data"] > atual[2] or melhor:
            ult[chave] = (l["carga_kg"], l["reps"], l["data"])
    return ult


# ---------------------------------------------------------------- formulário
def ler_form(form, treino):
    """Lê o formulário de registro. Devolve (dados, linhas, erros)."""
    erros = []
    status = form.get("status")
    if status not in STATUS:
        erros.append("Escolha se o treino foi feito, feito em parte ou não feito.")
    dados = {"status": status, "comentario": (form.get("comentario") or "").strip() or None,
             "rpe": None, "duracao_min": None, "data_realizada": None}
    d = (form.get("data_realizada") or "").strip()
    if d:
        try:
            dd = date.fromisoformat(d)
            if dd > date.today():
                erros.append("A data realizada não pode ser no futuro.")
            dados["data_realizada"] = dd.isoformat()
        except ValueError:
            erros.append("Data realizada inválida.")
    for campo, rot, lo, hi in (("rpe", "Esforço", 1, 10), ("duracao_min", "Duração", 1, 600)):
        v = (form.get(campo) or "").strip()
        if v:
            try:
                n = int(v)
                if not lo <= n <= hi:
                    raise ValueError
                dados[campo] = n
            except ValueError:
                erros.append(f"{rot}: informe um número de {lo} a {hi}.")
    linhas = []
    if status == "nao_feito":
        return dados, linhas, erros
    for it in treino["itens"]:
        iid = it["id"]
        if treino["modalidade"] == "corrida":
            nome = f"{it['tipo']} ({it['ordem']}º bloco)"
            reps = it["repeticoes"] or 1
            try:
                dist = treinos.ler_distancia(form.get(f"dist_{iid}"))
            except ValueError:
                erros.append(f"{nome}: distância não entendida.")
                continue
            if reps > 1:
                try:
                    tempos = ler_tempos_reps(form.get(f"tempos_{iid}"))
                except ValueError as e:
                    erros.append(f"{nome}: tempo “{e}” não entendido (ex.: 72 71 70 ou 1:12 1:11).")
                    continue
                if len(tempos) > 100:
                    erros.append(f"{nome}: tempos demais.")
                    continue
                if not tempos and not dist:
                    continue
                total_dist = (dist or 0) * (len(tempos) or reps)
                linhas.append({"item_id": iid, "distancia_m": total_dist or None,
                               "tempo_s": sum(tempos) or None, "tempos_reps": ",".join(f"{x:g}" for x in tempos) or None})
            else:
                tempo = (form.get(f"tempo_{iid}") or "").strip()
                seg = treinos.ler_duracao(tempo) if tempo else None
                if tempo and not seg:
                    erros.append(f"{nome}: tempo “{tempo}” não entendido (ex.: 42:30 ou 1:05:00).")
                    continue
                if not seg and not dist:
                    continue
                linhas.append({"item_id": iid, "distancia_m": dist, "tempo_s": seg, "tempos_reps": None})
        else:
            for k in range(1, (it["series"] or 0) + 1):
                c_txt, r_txt = form.get(f"carga_{iid}_{k}"), (form.get(f"reps_{iid}_{k}") or "").strip()
                if not (c_txt or "").strip() and not r_txt:
                    continue
                try:
                    carga = ler_carga(c_txt)
                    reps = int(r_txt) if r_txt else None
                    if reps is not None and not 0 <= reps <= 500:
                        raise ValueError
                except ValueError:
                    erros.append(f"{it['exercicio']}, série {k}: carga ou repetições inválidas.")
                    continue
                linhas.append({"item_id": iid, "serie": k, "carga_kg": carga, "reps": reps})
    if status in ("feito", "parcial") and not linhas and not erros:
        erros.append("Preencha pelo menos um " + ("bloco" if treino["modalidade"] == "corrida" else "exercício")
                     + " ou marque como não feito.")
    return dados, linhas, erros


def salvar(treino, dados, linhas):
    with db.Transacao() as t:
        t.execute("DELETE FROM registros WHERE treino_id = ?", (treino["id"],))  # filhos saem em cascata
        rid = t.insert("INSERT INTO registros (treino_id, status, data_realizada, duracao_min, rpe, comentario) "
                       "VALUES (?, ?, ?, ?, ?, ?)", (treino["id"], dados["status"], dados["data_realizada"],
                                                     dados["duracao_min"], dados["rpe"], dados["comentario"]))
        for l in linhas:
            if treino["modalidade"] == "corrida":
                t.insert("INSERT INTO registro_corrida (registro_id, item_id, distancia_m, tempo_s, tempos_reps) "
                         "VALUES (?, ?, ?, ?, ?)", (rid, l["item_id"], l["distancia_m"], l["tempo_s"], l["tempos_reps"]))
            else:
                t.insert("INSERT INTO registro_series (registro_id, item_id, serie, carga_kg, reps) VALUES (?, ?, ?, ?, ?)",
                         (rid, l["item_id"], l["serie"], l["carga_kg"], l["reps"]))
    return rid


# ---------------------------------------------------------------- realizado
def realizado(treino, reg):
    """Volume realizado da sessão (mesmas chaves do planejado) + carga interna (esforço × minutos)."""
    if not reg or reg["status"] == "nao_feito":
        base = {"metros": 0, "segundos": 0, "series": 0, "reps": 0, "kg": 0}
    elif treino["modalidade"] == "corrida":
        linhas = reg["corrida"].values()
        base = {"metros": sum(l["distancia_m"] or 0 for l in linhas), "segundos": round(sum(l["tempo_s"] or 0 for l in linhas))}
    else:
        todas = [s for lista in reg["series"].values() for s in lista]
        base = {"series": len(todas), "reps": sum(s["reps"] or 0 for s in todas),
                "kg": round(sum((s["carga_kg"] or 0) * (s["reps"] or 0) for s in todas))}
    dur = (reg or {}).get("duracao_min") or (round(base.get("segundos", 0) / 60) or None)
    base["carga_interna"] = (reg["rpe"] * dur) if reg and reg.get("rpe") and dur else 0
    return base


def comparar_blocos(treino, reg, paces):
    """Para cada bloco de corrida registrado: ritmo realizado × alvo (zona do aluno ou pace prescrito)."""
    saida = []
    if not reg or treino["modalidade"] != "corrida":
        return saida
    for it in treino["itens"]:
        l = reg["corrida"].get(it["id"])
        if not l or not l["distancia_m"] or not l["tempo_s"]:
            continue
        real = l["tempo_s"] / l["distancia_m"] * 1000
        zona = treinos.zona_do_bloco(it, paces)
        alvo = treinos.ler_pace(it.get("pace"))
        if not alvo and it.get("zona") and paces:
            alvo = paces[it["zona"]]
        saida.append({"item": it, "real": real, "alvo": alvo, "dif": (real - alvo) if alvo else None,
                      "zona": zona, "tempos": l["tempos"], "distancia_m": l["distancia_m"], "tempo_s": l["tempo_s"]})
    return saida


def sessoes(aluno_ids, de, ate):
    """Treinos (de todos os macrociclos dos alunos) no período, com planejado, registro e realizado."""
    ids = list(aluno_ids)
    if not ids:
        return []
    marca = ",".join("?" * len(ids))
    lista = db.query_all(
        f"SELECT t.*, m.aluno_id, m.nome AS macro_nome FROM treinos t JOIN macrociclos m ON m.id = t.macrociclo_id "
        f"WHERE m.aluno_id IN ({marca}) AND t.data BETWEEN ? AND ? ORDER BY t.data, t.id",
        (*ids, de.isoformat(), ate.isoformat()))
    if not lista:
        return []
    tids = [t["id"] for t in lista]
    m2 = ",".join("?" * len(tids))
    itens = {i: [] for i in tids}
    for it in db.query_all(f"SELECT * FROM treino_academia WHERE treino_id IN ({m2}) ORDER BY ordem", tids) + \
            db.query_all(f"SELECT * FROM treino_corrida WHERE treino_id IN ({m2}) ORDER BY ordem", tids):
        itens[it["treino_id"]].append(it)
    regs = carregar(tids)
    for t in lista:
        t["itens"] = itens[t["id"]]
        t["vol"] = treinos.volume(t["modalidade"], t["itens"])
        t["registro"] = regs.get(t["id"])
        t["real"] = realizado(t, t["registro"])
    return lista


def resumo(lista, hoje=None):
    """Totais de uma lista de sessões (só as que já deveriam ter acontecido: data <= hoje)."""
    hoje = (hoje or date.today()).isoformat()
    passadas = [t for t in lista if t["data"] <= hoje]
    feitas = [t for t in passadas if t["registro"] and t["registro"]["status"] in ("feito", "parcial")]
    rpes = [t["registro"]["rpe"] for t in feitas if t["registro"].get("rpe")]
    corr = [t for t in passadas if t["modalidade"] == "corrida"]
    acad = [t for t in passadas if t["modalidade"] == "academia"]
    return {
        "planejadas": len(passadas), "feitas": len(feitas),
        "registradas": sum(1 for t in passadas if t["registro"]),
        "adesao": round(100 * len(feitas) / len(passadas)) if passadas else None,
        "km_plan": sum(t["vol"]["metros"] for t in corr) / 1000, "km_real": sum(t["real"]["metros"] for t in corr) / 1000,
        "series_plan": sum(t["vol"]["series"] for t in acad), "series_real": sum(t["real"]["series"] for t in acad),
        "kg_real": sum(t["real"]["kg"] for t in acad),
        "rpe_medio": round(sum(rpes) / len(rpes), 1) if rpes else None,
        "carga_interna": sum(t["real"]["carga_interna"] for t in feitas),
        "ultimo": max((t["data"] for t in feitas), default=None),
    }


def semanas_calendario(lista, n=8, hoje=None):
    """Resumo por semana de calendário (segunda a domingo), das n últimas semanas até a atual."""
    hoje = hoje or date.today()
    seg = hoje - timedelta(days=hoje.weekday())
    saida = []
    for k in range(n - 1, -1, -1):
        ini = seg - timedelta(weeks=k)
        fim = ini + timedelta(days=6)
        da_semana = [t for t in lista if ini.isoformat() <= t["data"] <= fim.isoformat()]
        r = resumo(da_semana, min(hoje, fim))
        r.update(inicio=ini, fim=fim, atual=k == 0)
        saida.append(r)
    return saida


def progressao_cargas(aluno_id):
    """Por exercício: datas com a maior carga e a tonelagem do dia (para a evolução)."""
    linhas = db.query_all(
        "SELECT a.exercicio, t.data, s.carga_kg, s.reps FROM registro_series s "
        "JOIN registros r ON r.id = s.registro_id JOIN treinos t ON t.id = r.treino_id "
        "JOIN treino_academia a ON a.id = s.item_id JOIN macrociclos m ON m.id = t.macrociclo_id "
        "WHERE m.aluno_id = ? AND r.status <> 'nao_feito' ORDER BY t.data", (aluno_id,))
    ex = {}
    for l in linhas:
        nome = l["exercicio"].strip()
        dia = ex.setdefault(nome.lower(), {"nome": nome, "dias": {}})["dias"].setdefault(l["data"], {"max": 0, "ton": 0, "reps_max": 0})
        if l["carga_kg"] is not None:
            if l["carga_kg"] > dia["max"] or (l["carga_kg"] == dia["max"] and (l["reps"] or 0) > dia["reps_max"]):
                dia["max"], dia["reps_max"] = l["carga_kg"], l["reps"] or 0
            dia["ton"] += l["carga_kg"] * (l["reps"] or 0)
    saida = []
    for e in ex.values():
        pts = [{"data": d, **v} for d, v in sorted(e["dias"].items()) if v["max"]]
        if not pts:
            continue
        ini, fim = pts[0]["max"], pts[-1]["max"]
        saida.append({"nome": e["nome"], "pontos": pts, "primeira": ini, "ultima": fim, "maxima": max(p["max"] for p in pts),
                      "variacao": round(100 * (fim - ini) / ini) if ini else None, "sessoes": len(pts)})
    return sorted(saida, key=lambda e: (-e["sessoes"], e["nome"]))


def sparkline(valores, largura=120, altura=28):
    """Caminho SVG simples de uma série (para a evolução de carga)."""
    if not valores:
        return ""
    lo, hi = min(valores), max(valores)
    faixa = (hi - lo) or 1
    n = len(valores)
    pts = [(2 + (largura - 4) * (i / (n - 1) if n > 1 else .5), altura - 3 - (altura - 6) * (v - lo) / faixa)
           for i, v in enumerate(valores)]
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
