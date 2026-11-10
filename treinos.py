"""Treinos: prescrição de academia (exercícios) e corrida (blocos), por dia."""
import re
from datetime import date, timedelta

import daniels
import db

TIPOS_CORRIDA = ["Aquecimento", "Educativos", "Rodagem", "Regenerativo", "Longão", "Progressivo", "Fartlek",
                 "Limiar", "Intervalado", "Tiros", "Ritmo de prova", "Subidas", "Desaquecimento"]
# Blocos que contam como "qualidade" (intensidade) na corrida
TIPOS_QUALIDADE = {"Fartlek", "Limiar", "Intervalado", "Tiros", "Ritmo de prova", "Subidas", "Progressivo"}
PACE_PADRAO = 330  # 5:30/km — só para estimar o tempo de blocos com distância e sem tempo, no cálculo de intensidade
DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
DIAS_CURTOS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

CAMPOS = {
    "academia": ("exercicio", "series", "repeticoes", "carga", "descanso", "observacao"),
    "corrida": ("tipo", "zona", "repeticoes", "distancia", "duracao", "pace", "recuperacao", "observacao"),
}


# ---------------------------------------------------------------- distâncias
def ler_distancia(texto):
    """'400' -> 400 | '400m' -> 400 | '1,5 km' -> 1500 | '8km' -> 8000. Vazio -> None. Inválido -> ValueError."""
    t = (texto or "").strip().lower().replace(" ", "").replace(",", ".")
    if not t:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(km|k|m)?", t)
    if not m:
        raise ValueError(texto)
    valor, unidade = float(m.group(1)), m.group(2)
    if unidade in ("km", "k") or (unidade is None and valor < 50):  # "8" sem unidade = 8 km; "400" = 400 m
        valor *= 1000
    metros = round(valor)
    if not 1 <= metros <= 100000:
        raise ValueError(texto)
    return metros


def fmt_distancia(metros):
    if not metros:
        return ""
    if metros < 1000:
        return f"{metros} m"
    km = metros / 1000
    return (f"{km:.0f}" if km == int(km) else f"{km:.2f}".rstrip("0").replace(".", ",")) + " km"


# ---------------------------------------------------------------- tempo, pace e carga
def ler_duracao(texto):
    """Duração em segundos. Aceita: '72 s', '20 min', '1 min 30', "1'30", '1:12', '1:05:00', '1h10', '45'(=min).
    Texto que não é uma duração simples (ex.: '1 min forte / 1 min leve') -> None."""
    t = (texto or "").strip().lower().replace(",", ".").replace(" ", "")
    if not t:
        return None
    m = re.fullmatch(r"(\d+):(\d{1,2})(?::(\d{1,2}))?", t)
    if m:
        a, b, c = int(m.group(1)), int(m.group(2)), m.group(3)
        return a * 3600 + b * 60 + int(c) if c is not None else a * 60 + b
    t = t.replace("segundos", "s").replace("segundo", "s").replace("seg", "s").replace("minutos", "min") \
         .replace("minuto", "min").replace("horas", "h").replace("hora", "h").replace("''", '"')
    partes = re.findall(r"(\d+(?:\.\d+)?)(h|min|m|'|s|\")?", t)
    if not partes or "".join(n + u for n, u in partes) != t:
        return None
    total, anterior = 0.0, None
    for num, unid in partes:
        v = float(num)
        if not unid:  # sem unidade: depende do que veio antes
            unid = {"h": "min", "min": "s", "m": "s", "'": "s"}.get(anterior, "min")
        total += v * {"h": 3600, "min": 60, "m": 60, "'": 60, "s": 1, '"': 1}[unid]
        anterior = unid
    return round(total) if total > 0 else None


def fmt_duracao(seg):
    if not seg:
        return ""
    seg = round(seg)
    h, resto = divmod(seg, 3600)
    m, s = divmod(resto, 60)
    if h:
        return f"{h}h{m:02d}"
    if m and s:
        return f"{m} min {s:02d}" if m < 10 else f"{m} min"
    return f"{m} min" if m else f"{s} s"


PACE_MINIMO = 120  # 2:00/km — abaixo disso o valor é tempo da repetição, não pace por km


def ler_pace(texto):
    """Pace em segundos por km. Aceita '5:10', '5:10/km', "5'10". Outros formatos ou < 2:00/km -> None."""
    t = (texto or "").strip().lower().replace(" ", "").replace("min/km", "").replace("/km", "")
    m = re.fullmatch(r"(\d{1,2})[:'](\d{2})\"?", t)
    if not m:
        return None
    seg = int(m.group(1)) * 60 + int(m.group(2))
    return seg if seg >= PACE_MINIMO else None


def tempo_bloco(item):
    """Tempo de UMA repetição do bloco, em segundos (ou None).
    Ordem: duração; distância × pace/km; o 'pace' como tempo da repetição (ex.: 400 m @ 72 s)."""
    dur = ler_duracao(item.get("duracao"))
    if dur:
        return dur
    dist = item.get("distancia_m") or 0
    if not dist:
        return None
    pace = ler_pace(item.get("pace"))
    if pace:
        return dist / 1000 * pace
    if "/km" not in (item.get("pace") or "").lower():
        return ler_duracao(item.get("pace"))
    return None


def fmt_pace(seg_km):
    seg_km = round(seg_km)
    return f"{seg_km // 60}:{seg_km % 60:02d}/km"


def ler_kg(texto):
    """Carga em kg quando informada em kg ('60', '60 kg', '22,5kg'). Percentual ou texto -> None."""
    t = (texto or "").strip().lower().replace(" ", "").replace(",", ".")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(kg)?", t)
    return float(m.group(1)) if m else None


def ler_reps(texto):
    """Repetições para o cálculo de volume: '10' -> 10, '8–10' -> 9 (média). Tempo ('40 s') -> None."""
    t = (texto or "").strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d+)(?:[-–a](\d+))?(?:reps?)?", t)
    if not m:
        return None
    a, b = int(m.group(1)), m.group(2)
    return (a + int(b)) / 2 if b else a


def volume(modalidade, itens):
    """Volume planejado de uma sessão. 'completo' = False quando algum item não pôde ser somado."""
    if modalidade == "corrida":
        metros = segundos = 0
        completo = True
        for i in itens:
            reps = i.get("repeticoes") or 1
            metros += (i.get("distancia_m") or 0) * reps
            tempo = tempo_bloco(i)
            if tempo:
                segundos += tempo * reps
            else:
                completo = False
        return {"metros": metros, "segundos": round(segundos), "completo": completo}
    series = sum(i.get("series") or 0 for i in itens)
    reps = kg = 0.0
    completo = True
    for i in itens:
        r = ler_reps(i.get("repeticoes"))
        if r is None:
            completo = False
            continue
        reps += r * (i.get("series") or 0)
        c = ler_kg(i.get("carga"))
        if c is None:
            completo = False
        else:
            kg += c * r * (i.get("series") or 0)
    return {"series": series, "reps": round(reps), "kg": round(kg), "completo": completo}


def somar(vols):
    total = {"metros": 0, "segundos": 0, "series": 0, "reps": 0, "kg": 0, "sessoes": 0, "completo": True}
    for v in vols:
        total["sessoes"] += 1
        for k in ("metros", "segundos", "series", "reps", "kg"):
            total[k] += v.get(k, 0)
        total["completo"] = total["completo"] and v["completo"]
    return total


def fmt_km(metros):
    if not metros:
        return "0 km"
    km = metros / 1000
    return (f"{km:.0f}" if abs(km - round(km)) < 0.05 else f"{km:.1f}".replace(".", ",")) + " km"


def fmt_kg(kg):
    return f"{kg:,.0f}".replace(",", ".") + " kg"


def zona_do_bloco(item, paces=None):
    """Zona de Daniels do bloco: a escolhida; senão pelo pace (com os paces do aluno); senão pelo tipo."""
    if item.get("zona") in daniels.ZONAS:
        return item["zona"]
    if paces:
        seg_km = ler_pace(item.get("pace"))
        dist = item.get("distancia_m")
        if not seg_km and dist:  # "72 s" = tempo da repetição -> pace
            rep = ler_duracao(item.get("pace")) if "/km" not in (item.get("pace") or "").lower() else None
            seg_km = rep / dist * 1000 if rep else None
        if not seg_km and dist and ler_duracao(item.get("duracao")):
            seg_km = ler_duracao(item.get("duracao")) / dist * 1000
        if seg_km:
            return daniels.zona_do_pace(seg_km, paces)
    return daniels.ZONA_DO_TIPO.get(item.get("tipo"), "E")


def metricas_semanais(lista, inicio, paces=None):
    """Soma por semana do macrociclo (1, 2, ...) os dados do gráfico planejado e dos limites de Daniels.
    corrida:  metros, segundos, pontos (intensidade de Daniels) e metros/segundos por zona
    academia: series, reps_x_series e series_com_reps (para a média de reps por série)"""
    sem = {"corrida": {}, "academia": {}}
    for t in lista:
        w = semana_de(inicio, date.fromisoformat(t["data"]))
        if t["modalidade"] == "corrida":
            m = sem["corrida"].setdefault(w, {"metros": 0, "segundos": 0.0, "pontos": 0.0,
                                              "zonas": {z: {"metros": 0, "segundos": 0.0} for z in daniels.ZONAS}})
            for i in t["itens"]:
                reps = i.get("repeticoes") or 1
                dist = i.get("distancia_m") or 0
                z = zona_do_bloco(i, paces)
                tempo = tempo_bloco(i)
                if not tempo and dist:
                    tempo = dist / 1000 * (paces[z] if paces else PACE_PADRAO)
                tempo = (tempo or 0) * reps
                m["metros"] += dist * reps
                m["segundos"] += tempo
                m["pontos"] += tempo / 60 * daniels.PONTOS_POR_MIN[z]
                m["zonas"][z]["metros"] += dist * reps
                m["zonas"][z]["segundos"] += tempo
        else:
            m = sem["academia"].setdefault(w, {"series": 0, "reps_x_series": 0.0, "series_com_reps": 0})
            for i in t["itens"]:
                sr = i.get("series") or 0
                m["series"] += sr
                r = ler_reps(i.get("repeticoes"))
                if r is not None:
                    m["reps_x_series"] += r * sr
                    m["series_com_reps"] += sr
    for m in sem["corrida"].values():
        km = m["metros"] / 1000
        m["limites"] = daniels.limites_semana(km, {z: v["metros"] / 1000 for z, v in m["zonas"].items()})
        m["fora_limite"] = [z for z, l in m["limites"].items() if not l["ok"]]
    return sem


# ---------------------------------------------------------------- semanas
def inicio_semana(macro_inicio, n):
    return macro_inicio + timedelta(weeks=n - 1)


def semana_de(macro_inicio, dia):
    return (dia - macro_inicio).days // 7 + 1


# ---------------------------------------------------------------- leitura
def carregar(macro_id, de, ate):
    """Treinos do período com os itens, agrupados por data (ISO)."""
    lista = db.query_all("SELECT * FROM treinos WHERE macrociclo_id = ? AND data BETWEEN ? AND ? "
                         "ORDER BY data, CASE modalidade WHEN 'corrida' THEN 0 ELSE 1 END, id",
                         (macro_id, de.isoformat(), ate.isoformat()))
    if not lista:
        return {}
    ids = [t["id"] for t in lista]
    marca = ",".join("?" * len(ids))
    acad = db.query_all(f"SELECT * FROM treino_academia WHERE treino_id IN ({marca}) ORDER BY treino_id, ordem", ids)
    corr = db.query_all(f"SELECT * FROM treino_corrida WHERE treino_id IN ({marca}) ORDER BY treino_id, ordem", ids)
    itens = {i: [] for i in ids}
    for it in acad + corr:
        itens[it["treino_id"]].append(it)
    por_dia = {}
    for t in lista:
        t["itens"] = itens[t["id"]]
        t["vol"] = volume(t["modalidade"], t["itens"])
        por_dia.setdefault(t["data"], []).append(t)
    return por_dia


def um(treino_id):
    t = db.query_one("SELECT * FROM treinos WHERE id = ?", (treino_id,))
    if t:
        tabela = "treino_academia" if t["modalidade"] == "academia" else "treino_corrida"
        t["itens"] = db.query_all(f"SELECT * FROM {tabela} WHERE treino_id = ? ORDER BY ordem", (treino_id,))
    return t


def exercicios_usados(instrutor_id):
    """Nomes de exercícios já usados pelo professor (para sugestão e padronizar o histórico)."""
    return [r["exercicio"] for r in db.query_all(
        "SELECT DISTINCT a.exercicio FROM treino_academia a JOIN treinos t ON t.id = a.treino_id "
        "JOIN macrociclos m ON m.id = t.macrociclo_id JOIN usuarios u ON u.id = m.aluno_id "
        "WHERE u.instrutor_id = ? ORDER BY a.exercicio", (instrutor_id,))]


# ---------------------------------------------------------------- formulário
def ler_form(form, modalidade):
    """Lê o cabeçalho e as linhas do formulário. Devolve (dados, itens, erros)."""
    dados = {k: (form.get(k) or "").strip() or None for k in ("titulo", "observacoes", "data")}
    erros = []
    ids = form.getlist("item_id")
    colunas = {c: form.getlist(c) for c in CAMPOS[modalidade]}
    itens = []
    for i, item_id in enumerate(ids):
        linha = {c: (colunas[c][i] if i < len(colunas[c]) else "").strip() for c in CAMPOS[modalidade]}
        principal = linha["exercicio"] if modalidade == "academia" else linha["tipo"]
        if not principal and not any(v for k, v in linha.items() if k not in ("tipo", "zona", "series", "repeticoes")):
            continue  # linha em branco
        n = len(itens) + 1
        item = {"id": int(item_id) if item_id.isdigit() else None, **{k: v or None for k, v in linha.items()}}
        if modalidade == "academia":
            if not principal:
                erros.append(f"Exercício {n}: informe o nome.")
            try:
                item["series"] = int(linha["series"])
                if not 1 <= item["series"] <= 20:
                    raise ValueError
            except ValueError:
                erros.append(f"Exercício {n}: séries deve ser um número de 1 a 20.")
        else:
            if not principal:
                erros.append(f"Bloco {n}: escolha o tipo.")
            try:
                item["repeticoes"] = int(linha["repeticoes"] or 1)
                if not 1 <= item["repeticoes"] <= 100:
                    raise ValueError
            except ValueError:
                erros.append(f"Bloco {n}: repetições deve ser um número de 1 a 100.")
            try:
                item["distancia_m"] = ler_distancia(linha["distancia"])
            except ValueError:
                item["distancia_m"] = None
                erros.append(f"Bloco {n}: distância “{linha['distancia']}” não entendida (ex.: 400, 1,5 km, 8 km).")
            if not item["distancia_m"] and not item["duracao"] and principal:
                erros.append(f"Bloco {n}: informe a distância ou a duração.")
            if item["zona"] and item["zona"] not in daniels.ZONAS:
                item["zona"] = None
        itens.append(item)
    if not itens:
        erros.append("Adicione pelo menos um " + ("exercício." if modalidade == "academia" else "bloco."))
    return dados, itens, erros


def salvar(t, treino_id, modalidade, itens):
    """Grava os itens preservando os ids existentes (os registros do aluno ficam ligados a eles)."""
    tabela = "treino_academia" if modalidade == "academia" else "treino_corrida"
    existentes = {r["id"] for r in t.query_all(f"SELECT id FROM {tabela} WHERE treino_id = ?", (treino_id,))}
    manter = set()
    for ordem, it in enumerate(itens, 1):
        if modalidade == "academia":
            valores = (ordem, it["exercicio"], it["series"], it["repeticoes"], it["carga"], it["descanso"], it["observacao"])
            sets = "ordem = ?, exercicio = ?, series = ?, repeticoes = ?, carga = ?, descanso = ?, observacao = ?"
            cols = "ordem, exercicio, series, repeticoes, carga, descanso, observacao"
        else:
            valores = (ordem, it["tipo"], it.get("zona"), it["repeticoes"], it["distancia_m"], it["duracao"], it["pace"],
                       it["recuperacao"], it["observacao"])
            sets = ("ordem = ?, tipo = ?, zona = ?, repeticoes = ?, distancia_m = ?, duracao = ?, pace = ?, "
                    "recuperacao = ?, observacao = ?")
            cols = "ordem, tipo, zona, repeticoes, distancia_m, duracao, pace, recuperacao, observacao"
        if it.get("id") in existentes:
            t.execute(f"UPDATE {tabela} SET {sets} WHERE id = ?", (*valores, it["id"]))
            manter.add(it["id"])
        else:
            marcas = ", ".join("?" * (len(valores) + 1))
            t.insert(f"INSERT INTO {tabela} (treino_id, {cols}) VALUES ({marcas})", (treino_id, *valores))
    for removido in existentes - manter:
        t.execute(f"DELETE FROM {tabela} WHERE id = ?", (removido,))


def copiar(t, treino, nova_data, macro_id=None):
    """Cria uma cópia do treino (com os itens) em outra data."""
    novo = t.insert("INSERT INTO treinos (macrociclo_id, data, modalidade, titulo, observacoes) VALUES (?, ?, ?, ?, ?)",
                    (macro_id or treino["macrociclo_id"], nova_data.isoformat(), treino["modalidade"],
                     treino["titulo"], treino["observacoes"]))
    salvar(t, novo, treino["modalidade"], [{**i, "id": None} for i in treino["itens"]])
    return novo
