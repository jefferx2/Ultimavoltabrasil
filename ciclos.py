"""Periodização: modelos de fases, datas e dados para as visualizações."""
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
        "graficos": {m: grafico(g, total_semanas) for m, g in grupos.items() if g},
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


def grafico(fases, total_semanas, largura=640, altura=220, margem=(34, 12, 28, 12)):
    """Curvas de volume e intensidade (SVG) ao longo das semanas, com um ponto por fase."""
    esq, topo, base, dir_ = margem
    w, h = largura - esq - dir_, altura - topo - base

    def ponto(semana_meio, nivel):
        return (esq + semana_meio / total_semanas * w, topo + (5 - nivel) / 4 * h)

    pts = {"volume": [], "intensidade": []}
    for f in fases:
        meio = f["semana_ini"] - 1 + f["semanas"] / 2
        for k in pts:
            pts[k].append(ponto(meio, f[k]))

    def caminho(p):
        if len(p) == 1:
            return f"M{esq},{p[0][1]:.1f} L{esq + w},{p[0][1]:.1f}"
        # estende até as bordas e suaviza com curva monotônica (Fritsch–Carlson):
        # nunca passa acima/abaixo dos valores das fases
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

    divisorias = [esq + (f["semana_ini"] - 1) / total_semanas * w for f in fases[1:]]
    faixas = [{"x": esq + (f["semana_ini"] - 1) / total_semanas * w,
               "w": f["semanas"] / total_semanas * w, "cor": f["cor"], "nome": f["nome"]} for f in fases]
    return {
        "largura": largura, "altura": altura, "esq": esq, "topo": topo, "w": w, "h": h,
        "volume": caminho(pts["volume"]), "intensidade": caminho(pts["intensidade"]),
        "pontos": pts, "divisorias": divisorias, "faixas": faixas,
        "niveis": [(n, topo + (5 - n) / 4 * h) for n in range(1, 6)],
    }
