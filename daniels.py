"""Metodologia Jack Daniels: VDOT, paces de treino (E, M, T, I, R), faixas de volume e limites semanais.

VDOT pelas equações de Daniels & Gilbert (custo de O2 pela velocidade e fração do VO2máx sustentável
pelo tempo de prova). Frações de cada zona calibradas pelo exemplo da Daniels' Running Formula (VDOT 51:
E 4:52–5:29, M 4:27, T 4:11, I 3:51 /km, R 86 s/400 m). Diferenças de 1–2 s em relação às tabelas
impressas são arredondamento das tabelas.
"""
import math

ZONAS = ["E", "M", "T", "I", "R"]
NOMES_ZONAS = {"E": "Easy (leve)", "M": "Marathon (ritmo de maratona)", "T": "Threshold (limiar)",
               "I": "Interval (VO2máx)", "R": "Repetition (velocidade)"}
FRACAO = {"E_lento": 0.63, "E_rapido": 0.73, "T": 0.88, "I": 0.975, "R": 1.065}
PONTOS_POR_MIN = {"E": 0.2, "M": 0.4, "T": 0.6, "I": 1.0, "R": 1.5}  # intensidade de Daniels

# Faixas de volume semanal (km) por prova-alvo e nível — base informada pelo professor
FAIXAS = {
    "800": {"rotulo": "800 m", "baixa": (32, 48), "media": (64, 64), "alta": (80, 96)},
    "1500-3000": {"rotulo": "1500 m a 3000 m", "baixa": (48, 48), "media": (64, 80), "alta": (96, 112)},
    "5-10k": {"rotulo": "5 km e 10 km", "baixa": (48, 64), "media": (64, 80), "alta": (96, 112)},
    "meia": {"rotulo": "Meia maratona", "baixa": (50, 65), "media": (70, 95), "alta": (100, 130)},
}
NIVEIS_ALUNO = {"baixa": "Baixa (iniciante na prova)", "media": "Média (intermediário)",
                "alta": "Alta (avançado / competitivo)"}

# Distâncias aceitas para avaliação (prova recente ou teste)
DISTANCIAS_AVALIACAO = {
    "1500": ("1500 m", 1500), "milha": ("1 milha", 1609), "3000": ("3 km", 3000), "2milhas": ("2 milhas", 3219),
    "5000": ("5 km", 5000), "10000": ("10 km", 10000), "15000": ("15 km", 15000),
    "meia": ("Meia maratona", 21097), "maratona": ("Maratona", 42195), "cooper": ("Teste de 12 minutos", None),
}

# Limites semanais de Daniels: fração do volume semanal e teto absoluto em km (o que for menor)
LIMITES = {"T": (0.10, None), "I": (0.08, 10.0), "R": (0.05, 8.0)}


def _vo2(v):            # v em m/min -> ml/kg/min
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def _fracao_max(t):     # t em minutos -> fração do VO2máx sustentável
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t) + 0.2989558 * math.exp(-0.1932605 * t)


def _velocidade(vo2):   # inverso de _vo2
    a, b, c = 0.000104, 0.182258, -4.60 - vo2
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)


def vdot(distancia_m, tempo_s):
    t = tempo_s / 60
    return _vo2(distancia_m / t) / _fracao_max(t)


def prever_tempo(v, distancia_m):
    """Tempo de prova (s) previsto para o VDOT."""
    lo, hi = distancia_m / 1000 * 60, distancia_m / 1000 * 1200
    for _ in range(80):
        meio = (lo + hi) / 2
        if vdot(distancia_m, meio) > v:
            lo = meio
        else:
            hi = meio
    return (lo + hi) / 2


def _seg_km(fracao, v):
    return 60000 / _velocidade(fracao * v)


def paces(v):
    """Paces de treino em segundos por km. E é uma faixa (rápido, lento); usa-se o meio para preencher."""
    e_rap, e_len = _seg_km(FRACAO["E_rapido"], v), _seg_km(FRACAO["E_lento"], v)
    return {
        "E": (e_rap + e_len) / 2, "E_faixa": (e_rap, e_len),
        "M": prever_tempo(v, 42195) / 42.195,
        "T": _seg_km(FRACAO["T"], v), "I": _seg_km(FRACAO["I"], v), "R": _seg_km(FRACAO["R"], v),
    }


def zona_do_pace(seg_km, p):
    """Classifica um pace (s/km) pela zona mais próxima entre os paces do aluno (fronteiras nos pontos médios)."""
    ordem = [("E", p["E_faixa"][0]), ("M", p["M"]), ("T", p["T"]), ("I", p["I"]), ("R", p["R"])]
    for (z1, p1), (_, p2) in zip(ordem, ordem[1:]):
        if seg_km >= (p1 + p2) / 2:
            return z1
    return "R"


# Zona presumida pelo tipo do bloco, quando não há zona escolhida nem pace
ZONA_DO_TIPO = {"Aquecimento": "E", "Educativos": "E", "Rodagem": "E", "Regenerativo": "E", "Longão": "E",
                "Desaquecimento": "E", "Progressivo": "M", "Fartlek": "T", "Limiar": "T", "Intervalado": "I",
                "Tiros": "R", "Ritmo de prova": "I", "Subidas": "R"}


def faixa(categoria, nivel):
    f = FAIXAS.get(categoria or "")
    if not f or nivel not in NIVEIS_ALUNO:
        return None
    lo, hi = f[nivel]
    return {"min": lo, "max": hi, "rotulo": f["rotulo"], "nivel": NIVEIS_ALUNO[nivel],
            "texto": f"{lo} km/sem" if lo == hi else f"{lo} a {hi} km/sem"}


def limites_semana(km_total, km_zona):
    """Confere os limites de Daniels de uma semana. Devolve {zona: {km, pct, limite_km, ok}}."""
    saida = {}
    for z, (frac, teto) in LIMITES.items():
        limite = km_total * frac if teto is None else min(teto, km_total * frac)
        km = km_zona.get(z, 0.0)
        saida[z] = {"km": km, "pct": 100 * km / km_total if km_total else 0, "limite_km": limite,
                    "limite_txt": f"{int(frac * 100)}%" + (f" ou {teto:g} km" if teto else ""),
                    "ok": km <= limite + 0.05}
    return saida


def fmt_pace(seg_km):
    s = round(seg_km)
    return f"{s // 60}:{s % 60:02d}/km"


def fmt_tempo(seg):
    s = round(seg)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def tempo_rep(seg_km, metros):
    """Tempo de uma repetição curta no pace dado (ex.: 400 m @ 3:40/km -> '1:28')."""
    return fmt_tempo(seg_km * metros / 1000)
