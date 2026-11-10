"""Treinos: prescrição de academia (exercícios) e corrida (blocos), por dia."""
import re
from datetime import date, timedelta

import db

TIPOS_CORRIDA = ["Aquecimento", "Educativos", "Rodagem", "Regenerativo", "Longão", "Progressivo", "Fartlek",
                 "Limiar", "Intervalado", "Tiros", "Ritmo de prova", "Subidas", "Desaquecimento"]
DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
DIAS_CURTOS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

CAMPOS = {
    "academia": ("exercicio", "series", "repeticoes", "carga", "descanso", "observacao"),
    "corrida": ("tipo", "repeticoes", "distancia", "duracao", "pace", "recuperacao", "observacao"),
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
        if t["modalidade"] == "corrida":
            t["metros"] = sum((i["distancia_m"] or 0) * i["repeticoes"] for i in t["itens"])
        else:
            t["series_total"] = sum(i["series"] for i in t["itens"])
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
        if not principal and not any(v for k, v in linha.items() if k not in ("tipo", "series", "repeticoes")):
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
            valores = (ordem, it["tipo"], it["repeticoes"], it["distancia_m"], it["duracao"], it["pace"],
                       it["recuperacao"], it["observacao"])
            sets = "ordem = ?, tipo = ?, repeticoes = ?, distancia_m = ?, duracao = ?, pace = ?, recuperacao = ?, observacao = ?"
            cols = "ordem, tipo, repeticoes, distancia_m, duracao, pace, recuperacao, observacao"
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
