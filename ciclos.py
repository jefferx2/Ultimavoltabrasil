"""Periodização: modelos de fases, datas e dados para as visualizações."""
import math
from datetime import date, timedelta

MODALIDADES = {"academia": "Academia", "corrida": "Corrida"}
NIVEIS = {1: "Muito baixa", 2: "Baixa", 3: "Moderada", 4: "Alta", 5: "Muito alta"}
NIVEIS_VOLUME = {1: "Muito baixo", 2: "Baixo", 3: "Moderado", 4: "Elevado", 5: "Muito elevado"}
CORES = ["#8a8f98", "#3d7ea6", "#e0a100", "#d7262e", "#5a9e6f", "#7a4fa3", "#c4682b", "#2a9d8f"]

SEMANAS_TRANSICAO = 2

# Periodização linear com 5 fases (modelo para atletas). A Fase 5 é a transição pós-competição.
# peso = participação nas semanas até a competição (fases 1 a 4)
MODELOS = {
    "academia": [
        dict(nome="Endurance-Hipertrofia", objetivo="Resistência muscular e adaptação estrutural",
             series="3–5", repeticoes="15–20", intensidade=2, volume=5, peso=35),
        dict(nome="Hipertrofia", objetivo="Aumento de massa muscular",
             series="3–5", repeticoes="8–10", intensidade=3, volume=4, peso=30),
        dict(nome="Potência", objetivo="Produção de força rápida",
             series="3–5", repeticoes="4–6", intensidade=4, volume=3, peso=20),
        dict(nome="Pico de Força e Potência", objetivo="Máxima expressão de força e potência",
             series="1–3", repeticoes="1–3", intensidade=5, volume=2, peso=15),
        dict(nome="Transição", objetivo="Recuperação ativa",
             series="1–2", repeticoes="8–10", intensidade=3, volume=2, peso=None),
    ],
    "corrida": [
        dict(nome="Base Aeróbica", objetivo="Volume aeróbico, rodagens e longões em ritmo confortável",
             intensidade=2, volume=5, peso=35),
        dict(nome="Desenvolvimento", objetivo="Limiar, fartlek e progressivos",
             intensidade=3, volume=4, peso=30),
        dict(nome="Específico", objetivo="VO2máx, tiros e ritmo de prova",
             intensidade=4, volume=3, peso=20),
        dict(nome="Polimento / Pico", objetivo="Ritmo de prova com volume reduzido",
             intensidade=5, volume=2, peso=15),
        dict(nome="Transição", objetivo="Regenerativos e descanso ativo",
             intensidade=2, volume=2, peso=None),
    ],
}


def semanas_ate(inicio, competicao):
    """Semanas inteiras do início até a semana da competição (inclusive)."""
    return max(1, (competicao - inicio).days // 7 + 1)


def distribuir(total, pesos):
    """Divide `total` semanas pelos pesos (mínimo 1 por fase), somando exatamente `total`."""
    n = len(pesos)
    if total <= n:
        return [1] * n
    # 1 semana garantida por fase; o restante pelo método do maior resto
    resto_total = total - n
    exatos = [resto_total * p / sum(pesos) for p in pesos]
    base = [1 + int(e) for e in exatos]
    sobra = total - sum(base)
    for k in sorted(range(n), key=lambda k: (-(exatos[k] - int(exatos[k])), -pesos[k]))[:sobra]:
        base[k] += 1
    return base


def fases_modelo(modalidade, inicio, competicao=None):
    """Fases do modelo padrão com semanas calculadas para o pico cair na competição."""
    modelo = MODELOS[modalidade]
    pre = [f for f in modelo if f["peso"]]
    total = semanas_ate(inicio, competicao) if competicao else 16
    semanas = distribuir(total, [f["peso"] for f in pre]) + [SEMANAS_TRANSICAO]
    return [{**{k: v for k, v in f.items() if k != "peso"}, "semanas": s, "ordem": i + 1}
            for i, (f, s) in enumerate(zip(modelo, semanas))]


def com_datas(fases, inicio):
    """Acrescenta inicio/fim/semana inicial a cada fase (em ordem)."""
    atual, semana = inicio, 1
    saida = []
    for i, f in enumerate(fases):
        fim = atual + timedelta(weeks=f["semanas"]) - timedelta(days=1)
        saida.append({**f, "inicio": atual, "fim": fim, "semana_ini": semana,
                      "cor": CORES[i % len(CORES)]})
        atual = fim + timedelta(days=1)
        semana += f["semanas"]
    return saida


def fase_atual(fases_datadas, hoje):
    for f in fases_datadas:
        if f["inicio"] <= hoje <= f["fim"]:
            semana_na_fase = (hoje - f["inicio"]).days // 7 + 1
            return {"fase": f, "semana": semana_na_fase}
    return None


def montar(macro, fases, hoje=None):
    """Organiza um macrociclo para exibição: fases por modalidade com datas, totais e gráficos."""
    hoje = hoje or date.today()
    inicio = date.fromisoformat(macro["data_inicio"])
    comp = date.fromisoformat(macro["data_competicao"]) if macro.get("data_competicao") else None

    grupos = {}
    for m in MODALIDADES:
        lista = sorted((f for f in fases if f["modalidade"] == m), key=lambda f: f["ordem"])
        grupos[m] = com_datas(lista, inicio)

    total_semanas = max([sum(f["semanas"] for f in g) for g in grupos.values()] + [1])
    fim = inicio + timedelta(weeks=total_semanas) - timedelta(days=1)

    def pos(d):  # posição (0–100%) de uma data na linha do tempo
        return max(0.0, min(100.0, (d - inicio).days / ((fim - inicio).days + 1) * 100))

    for g in grupos.values():
        for f in g:
            f["x"] = pos(f["inicio"])
            f["w"] = pos(f["fim"] + timedelta(days=1)) - f["x"]

    # Aviso: o pico (penúltima fase, antes da transição) deveria conter a competição
    avisos = {}
    if comp:
        for m, g in grupos.items():
            if len(g) >= 2 and not (g[-2]["inicio"] <= comp <= g[-2]["fim"]):
                avisos[m] = (f"A competição ({comp.strftime('%d/%m/%Y')}) não cai na fase "
                             f"“{g[-2]['nome']}”. Ajuste as semanas para o pico coincidir.")

    return {
        "inicio": inicio, "fim": fim, "competicao": comp, "total_semanas": total_semanas,
        "grupos": grupos, "avisos": avisos,
        "hoje": hoje, "hoje_x": pos(hoje) if inicio <= hoje <= fim else None,
        "comp_x": pos(comp) if comp and inicio <= comp <= fim else None,
        "atual": {m: fase_atual(g, hoje) for m, g in grupos.items()},
        "graficos": {m: grafico(g, total_semanas, inicio) for m, g in grupos.items() if g},
        "marcas": marcas_meses(inicio, fim, pos),
    }


def marcas_meses(inicio, fim, pos):
    meses = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    d = date(inicio.year, inicio.month, 1)
    saida = []
    while d <= fim:
        if d >= inicio:
            saida.append({"x": pos(d), "rotulo": meses[d.month - 1] + ("/" + str(d.year)[2:] if d.month == 1 else "")})
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return saida


def grafico(fases, total_semanas, inicio=None, plan=None, acima=None,
            largura=720, altura=270, margem=(34, 26, 40, 12)):
    """SVG: curvas da metodologia (por fase) e do planejado (por semana), com eixo de datas.
    Escala vertical de 0 a 5 (ou mais, se o planejado passar de 5)."""
    esq, topo, base, dir_ = margem
    w, h = largura - esq - dir_, altura - topo - base
    plan = plan or {"volume": {}, "intensidade": {}}
    acima = acima or {"volume": set(), "intensidade": set()}
    maior = max([v for c in ("volume", "intensidade") for v in plan[c].values()] + [5])
    ymax = min(8, max(5, math.ceil(maior)))

    def y(nivel):
        return topo + (ymax - min(nivel, ymax)) / ymax * h

    def x_sem(semana_float):
        return esq + semana_float / total_semanas * w

    # metodologia: um ponto no meio de cada fase, curva suave sem ultrapassar os níveis
    pts = {"volume": [], "intensidade": []}
    for f in fases:
        meio = f["semana_ini"] - 1 + f["semanas"] / 2
        for k in pts:
            pts[k].append((x_sem(meio), y(f[k])))

    def caminho(p):
        if not p:
            return ""
        if len(p) == 1:
            return f"M{esq},{p[0][1]:.1f} L{esq + w},{p[0][1]:.1f}"
        p = [(esq, p[0][1])] + p + [(esq + w, p[-1][1])]
        n = len(p)
        dx = [p[i + 1][0] - p[i][0] or 1e-9 for i in range(n - 1)]
        sec = [(p[i + 1][1] - p[i][1]) / dx[i] for i in range(n - 1)]
        m = [sec[0]] + [0.0 if sec[i - 1] * sec[i] <= 0 else
                        3 * (dx[i - 1] + dx[i]) / ((2 * dx[i] + dx[i - 1]) / sec[i - 1] + (dx[i] + 2 * dx[i - 1]) / sec[i])
                        for i in range(1, n - 1)] + [sec[-1]]
        d = f"M{p[0][0]:.1f},{p[0][1]:.1f}"
        for i in range(n - 1):
            c1 = (p[i][0] + dx[i] / 3, p[i][1] + m[i] * dx[i] / 3)
            c2 = (p[i + 1][0] - dx[i] / 3, p[i + 1][1] - m[i + 1] * dx[i] / 3)
            d += f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p[i + 1][0]:.1f},{p[i + 1][1]:.1f}"
        return d

    # planejado: um ponto por semana com treino; semanas sem treino interrompem a linha
    plan_pts, plan_path = {}, {}
    for campo in ("volume", "intensidade"):
        semanas = sorted(s_ for s_ in plan[campo] if 1 <= s_ <= total_semanas)
        plan_pts[campo] = [{"x": x_sem(s_ - 0.5), "y": y(plan[campo][s_]), "semana": s_,
                            "nivel": plan[campo][s_], "acima": s_ in acima[campo]} for s_ in semanas]
        d, anterior = "", None
        for pt in plan_pts[campo]:
            d += (" L" if anterior is not None and pt["semana"] == anterior + 1 else " M") + f"{pt['x']:.1f},{pt['y']:.1f}"
            anterior = pt["semana"]
        plan_path[campo] = d.strip()

    meses = []
    if inicio:
        nomes = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
        fim = inicio + timedelta(weeks=total_semanas)
        d0 = date(inicio.year + (inicio.month == 12), inicio.month % 12 + 1, 1)
        while d0 < fim:
            meses.append({"x": x_sem((d0 - inicio).days / 7),
                          "rotulo": nomes[d0.month - 1] + (f"/{str(d0.year)[2:]}" if d0.month == 1 else "")})
            d0 = date(d0.year + (d0.month == 12), d0.month % 12 + 1, 1)

    return {
        "largura": largura, "altura": altura, "esq": esq, "topo": topo, "w": w, "h": h, "ymax": ymax,
        "volume": caminho(pts["volume"]), "intensidade": caminho(pts["intensidade"]), "pontos": pts,
        "plan_path": plan_path, "plan_pts": plan_pts, "meses": meses,
        "divisorias": [x_sem(f["semana_ini"] - 1) for f in fases[1:]],
        "faixas": [{"x": x_sem(f["semana_ini"] - 1), "w": f["semanas"] / total_semanas * w,
                    "cor": f["cor"], "nome": f["nome"], "ordem": f["ordem"]} for f in fases],
        "niveis": [(n, y(n)) for n in range(0, ymax + 1)],
        "y5": y(5),
    }


# ---------------------------------------------------------------- planejado na escala 1–5
# Intensidade da academia pela média de repetições por série (mesma lógica da tabela do modelo):
# 15–20 reps = baixa (2) · 8–10 = moderada (3) · 4–6 = alta (4) · 1–3 = muito alta (5)
ANCORAS_REPS = [(20, 1.5), (17.5, 2), (9, 3), (5, 4), (2, 5)]
# Intensidade da corrida pela % do tempo em blocos de qualidade
ANCORAS_QUALIDADE = [(0, 1.5), (10, 2), (20, 3), (30, 4), (40, 5)]
TOLERANCIA = 0.5  # acima da metodologia por mais que isso = alerta


def _interpolar(x, ancoras):
    pts = sorted(ancoras)
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def niveis_planejados(metricas, modalidade, referencia=None):
    """Converte as métricas semanais em níveis 1–5 (podem passar de 5 quando a semana excede a referência).
    Volume: nível = 5 × valor / referência (referência = valor do nível 5). Sem referência: maior semana planejada."""
    if modalidade == "corrida":
        vol = {w: m["metros"] / 1000 for w, m in metricas.items()}
        intens = {w: _interpolar(100 * m["segundos_qualidade"] / m["segundos"], ANCORAS_QUALIDADE)
                  for w, m in metricas.items() if m["segundos"]}
    else:
        vol = {w: m["series"] for w, m in metricas.items()}
        intens = {w: _interpolar(m["reps_x_series"] / m["series_com_reps"], ANCORAS_REPS)
                  for w, m in metricas.items() if m["series_com_reps"]}
    relativa = not referencia
    ref = referencia or max(vol.values(), default=0)
    niveis_vol = {w: 5 * v / ref for w, v in vol.items()} if ref else {}
    return {"volume": niveis_vol, "intensidade": intens, "bruto": vol, "referencia": ref, "relativa": relativa}


def nivel_da_semana(fases, semana, campo):
    for f in fases:
        if f["semana_ini"] <= semana < f["semana_ini"] + f["semanas"]:
            return f[campo]
    return None


def excessos(fases, plan):
    """Semanas em que o planejado passa da metodologia (por campo), e contagem por fase."""
    acima = {"volume": set(), "intensidade": set()}
    for campo in acima:
        for w, nivel in plan[campo].items():
            meta = nivel_da_semana(fases, w, campo)
            if meta is not None and nivel > meta + TOLERANCIA:
                acima[campo].add(w)
    for f in fases:
        semanas = range(f["semana_ini"], f["semana_ini"] + f["semanas"])
        f["acima"] = {c: sum(1 for w in semanas if w in acima[c]) for c in acima}
    return acima
