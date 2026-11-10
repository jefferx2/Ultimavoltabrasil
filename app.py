"""Última Volta Brasil — sistema de treinos (instrutor / aluno)."""
import os
import re
import secrets
from datetime import date, timedelta
from functools import wraps

import click
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import ciclos
import daniels
import db
import treinos

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV") == "production"

db.init_db()

SENHA_MIN = 8
PROVAS_SUGERIDAS = ["800 m", "1500 m", "3000 m", "5 km", "10 km", "21 km", "42 km"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------- utilidades
def usuario_atual():
    if "usuario" not in g:
        uid = session.get("uid")
        g.usuario = db.query_one(
            "SELECT id, nome, email, perfil, trocar_senha FROM usuarios WHERE id = ? AND ativo = 1",
            (uid,)) if uid else None
    return g.usuario


def login_obrigatorio(perfil=None):
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = usuario_atual()
            if not user:
                return redirect(url_for("login", next=request.path))
            if perfil and user["perfil"] != perfil:
                abort(403)
            return view(*args, user=user, **kwargs)
        return wrapper
    return deco


def destino_por_perfil(perfil):
    return url_for("painel_instrutor") if perfil == "instrutor" else url_for("painel_aluno")


def gerar_senha(n=10):
    alfabeto = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sem 0/O, 1/l/I
    return "".join(secrets.choice(alfabeto) for _ in range(n))


def idade(data_iso):
    try:
        nasc = date.fromisoformat(data_iso)
    except (TypeError, ValueError):
        return None
    hoje = date.today()
    return hoje.year - nasc.year - ((hoje.month, hoje.day) < (nasc.month, nasc.day))


@app.template_filter("data_br")
def data_br(valor):
    try:
        return date.fromisoformat(str(valor)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return valor or ""


app.add_template_filter(treinos.fmt_km, "km")
app.add_template_filter(daniels.fmt_pace, "pace")
app.add_template_filter(daniels.fmt_tempo, "tempo")


@app.template_filter("dias_desde")
def dias_desde(hoje_iso, data_iso):
    return (date.fromisoformat(hoje_iso) - date.fromisoformat(str(data_iso)[:10])).days


@app.template_filter("numero")
def numero(v):
    """Número sem casas desnecessárias e com vírgula ('60', '42,5'); vazio para None."""
    if not v and v != 0:  # None, "", ou ausente (Undefined)
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return (f"{f:.0f}" if f == int(f) else f"{f:g}").replace(".", ",")
app.add_template_filter(treinos.fmt_duracao, "duracao")
app.add_template_filter(treinos.fmt_kg, "kg")


@app.template_filter("data_curta")
def data_curta(valor):
    try:
        return date.fromisoformat(str(valor)[:10]).strftime("%d/%m")
    except ValueError:
        return valor or ""


@app.before_request
def antes():
    if request.method == "POST":
        token = session.get("csrf")
        if not token or token != request.form.get("csrf"):
            abort(400)
    # Troca de senha obrigatória (1º acesso ou senha redefinida pelo professor)
    user = usuario_atual()
    if user and user["trocar_senha"] and request.endpoint not in ("trocar_senha", "sair", "static"):
        return redirect(url_for("trocar_senha"))


@app.context_processor
def injetar():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return {"csrf_token": session["csrf"], "usuario": usuario_atual(),
            "MODALIDADES": ciclos.MODALIDADES, "NIVEIS": ciclos.NIVEIS, "NIVEIS_VOLUME": ciclos.NIVEIS_VOLUME}


# ---------------------------------------------------------------- públicas / login
@app.route("/")
def home():
    return render_template("home.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    user = usuario_atual()
    if user:
        return redirect(destino_por_perfil(user["perfil"]))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        row = db.query_one("SELECT * FROM usuarios WHERE email = ? AND ativo = 1", (email,))
        if row and check_password_hash(row["senha_hash"], senha):
            session.clear()
            session["uid"] = row["id"]
            session["csrf"] = secrets.token_hex(16)
            if row["trocar_senha"]:
                return redirect(url_for("trocar_senha"))
            nxt = request.args.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(destino_por_perfil(row["perfil"]))
        flash("E-mail ou senha incorretos.", "erro")
    return render_template("login.html")


@app.route("/sair")
def sair():
    session.clear()
    return redirect(url_for("home"))


@app.route("/trocar-senha", methods=["GET", "POST"])
@login_obrigatorio()
def trocar_senha(user):
    if request.method == "POST":
        atual = request.form.get("atual", "")
        nova = request.form.get("nova", "")
        conf = request.form.get("confirmacao", "")
        row = db.query_one("SELECT senha_hash FROM usuarios WHERE id = ?", (user["id"],))
        if not check_password_hash(row["senha_hash"], atual):
            flash("Senha atual incorreta.", "erro")
        elif len(nova) < SENHA_MIN:
            flash(f"A nova senha precisa ter pelo menos {SENHA_MIN} caracteres.", "erro")
        elif nova != conf:
            flash("A confirmação não confere com a nova senha.", "erro")
        elif nova == atual:
            flash("A nova senha precisa ser diferente da atual.", "erro")
        else:
            db.execute("UPDATE usuarios SET senha_hash = ?, trocar_senha = 0 WHERE id = ?",
                       (generate_password_hash(nova), user["id"]))
            flash("Senha alterada.", "ok")
            return redirect(destino_por_perfil(user["perfil"]))
    return render_template("trocar_senha.html", obrigatoria=bool(user["trocar_senha"]), senha_min=SENHA_MIN)


# ---------------------------------------------------------------- instrutor
@app.route("/instrutor")
@login_obrigatorio("instrutor")
def painel_instrutor(user):
    total = db.query_one(
        "SELECT COUNT(*) AS n FROM usuarios WHERE perfil = 'aluno' AND ativo = 1 AND instrutor_id = ?",
        (user["id"],))["n"]
    total_macros = db.query_one(
        "SELECT COUNT(*) AS n FROM macrociclos m JOIN usuarios u ON u.id = m.aluno_id "
        "WHERE u.instrutor_id = ? AND u.ativo = 1", (user["id"],))["n"]
    return render_template("painel_instrutor.html", total_alunos=total, total_macros=total_macros)


def perfil_corrida(aluno):
    """VDOT (avaliação mais recente), paces de treino e faixa de volume do aluno."""
    aval = db.query_one("SELECT * FROM avaliacoes WHERE aluno_id = ? ORDER BY data DESC, id DESC LIMIT 1",
                        (aluno["id"],))
    p = daniels.paces(aval["vdot"]) if aval else None
    return {
        "avaliacao": aval, "vdot": aval["vdot"] if aval else None, "paces": p,
        "faixa": daniels.faixa(aluno.get("prova_categoria"), aluno.get("nivel")),
        "zonas_js": {z: round(p[z]) for z in daniels.ZONAS} if p else {},
    }


def _aluno_do_instrutor(aluno_id, instrutor_id):
    aluno = db.query_one(
        "SELECT * FROM usuarios WHERE id = ? AND perfil = 'aluno' AND instrutor_id = ?",
        (aluno_id, instrutor_id))
    if not aluno:
        abort(404)
    return aluno


def _validar_aluno(form, aluno_id=None):
    dados = {
        "nome": form.get("nome", "").strip(),
        "email": form.get("email", "").strip().lower(),
        "data_nascimento": form.get("data_nascimento", "").strip() or None,
        "prova_principal": form.get("prova_principal", "").strip() or None,
        "telefone": form.get("telefone", "").strip() or None,
        "observacoes": form.get("observacoes", "").strip() or None,
        "prova_categoria": form.get("prova_categoria", "").strip() or None,
        "nivel": form.get("nivel", "").strip() or None,
    }
    erros = []
    if dados["prova_categoria"] and dados["prova_categoria"] not in daniels.FAIXAS:
        erros.append("Prova-alvo inválida.")
    if dados["nivel"] and dados["nivel"] not in daniels.NIVEIS_ALUNO:
        erros.append("Nível inválido.")
    for campo, rotulo, minimo, maximo, tipo in (("volume_atual_km", "Volume semanal atual", 0, 300, float),
                                                ("dias_semana", "Dias disponíveis", 1, 7, int)):
        txt = (form.get(campo) or "").strip().replace(",", ".")
        dados[campo] = None
        if txt:
            try:
                v = float(txt)
                if not minimo <= v <= maximo or (tipo is int and v != int(v)):
                    raise ValueError
                dados[campo] = tipo(v)
            except ValueError:
                erros.append(f"{rotulo}: informe um número de {minimo} a {maximo}.")
    if not dados["nome"]:
        erros.append("Informe o nome.")
    if not EMAIL_RE.match(dados["email"]):
        erros.append("Informe um e-mail válido.")
    else:
        outro = db.query_one("SELECT id FROM usuarios WHERE email = ?", (dados["email"],))
        if outro and outro["id"] != aluno_id:
            erros.append("Já existe um usuário com esse e-mail.")
    if dados["data_nascimento"]:
        try:
            if date.fromisoformat(dados["data_nascimento"]) > date.today():
                erros.append("Data de nascimento no futuro.")
        except ValueError:
            erros.append("Data de nascimento inválida.")
    return dados, erros


@app.route("/instrutor/alunos")
@login_obrigatorio("instrutor")
def alunos(user):
    mostrar = request.args.get("mostrar", "ativos")
    filtro = "" if mostrar == "todos" else "AND ativo = 1"
    lista = db.query_all(
        f"SELECT * FROM usuarios WHERE perfil = 'aluno' AND instrutor_id = ? {filtro} ORDER BY nome",
        (user["id"],))
    for a in lista:
        a["idade"] = idade(a["data_nascimento"])
    return render_template("alunos.html", alunos=lista, mostrar=mostrar)


@app.route("/instrutor/alunos/novo", methods=["GET", "POST"])
@login_obrigatorio("instrutor")
def aluno_novo(user):
    dados = {}
    if request.method == "POST":
        dados, erros = _validar_aluno(request.form)
        senha = request.form.get("senha", "").strip() or gerar_senha()
        if len(senha) < SENHA_MIN:
            erros.append(f"A senha inicial precisa ter pelo menos {SENHA_MIN} caracteres.")
        if erros:
            for e in erros:
                flash(e, "erro")
        else:
            db.execute(
                "INSERT INTO usuarios (nome, email, senha_hash, perfil, instrutor_id, data_nascimento, "
                "prova_principal, telefone, observacoes, prova_categoria, nivel, volume_atual_km, dias_semana, "
                "trocar_senha) VALUES (?, ?, ?, 'aluno', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (dados["nome"], dados["email"], generate_password_hash(senha), user["id"],
                 dados["data_nascimento"], dados["prova_principal"], dados["telefone"], dados["observacoes"],
                 dados["prova_categoria"], dados["nivel"], dados["volume_atual_km"], dados["dias_semana"]))
            return render_template("aluno_acesso.html", nome=dados["nome"], email=dados["email"],
                                   senha=senha, titulo="Aluno cadastrado")
    return render_template("aluno_form.html", aluno=dados, novo=True, provas=PROVAS_SUGERIDAS, senha_min=SENHA_MIN,
                           d=daniels)


@app.route("/instrutor/alunos/<int:aluno_id>", methods=["GET", "POST"])
@login_obrigatorio("instrutor")
def aluno_editar(user, aluno_id):
    aluno = _aluno_do_instrutor(aluno_id, user["id"])
    if request.method == "POST":
        dados, erros = _validar_aluno(request.form, aluno_id)
        if erros:
            for e in erros:
                flash(e, "erro")
            aluno.update(dados)
        else:
            db.execute(
                "UPDATE usuarios SET nome = ?, email = ?, data_nascimento = ?, prova_principal = ?, "
                "telefone = ?, observacoes = ?, prova_categoria = ?, nivel = ?, volume_atual_km = ?, "
                "dias_semana = ? WHERE id = ?",
                (dados["nome"], dados["email"], dados["data_nascimento"], dados["prova_principal"],
                 dados["telefone"], dados["observacoes"], dados["prova_categoria"], dados["nivel"],
                 dados["volume_atual_km"], dados["dias_semana"], aluno_id))
            flash("Dados do aluno salvos.", "ok")
            return redirect(url_for("alunos"))
    macros = db.query_all("SELECT * FROM macrociclos WHERE aluno_id = ? ORDER BY data_inicio DESC", (aluno_id,))
    avaliacoes = db.query_all("SELECT * FROM avaliacoes WHERE aluno_id = ? ORDER BY data DESC, id DESC", (aluno_id,))
    return render_template("aluno_form.html", aluno=aluno, novo=False, provas=PROVAS_SUGERIDAS,
                           senha_min=SENHA_MIN, macros=macros, avaliacoes=avaliacoes,
                           perfil=perfil_corrida(aluno), d=daniels, hoje=date.today().isoformat())


@app.route("/instrutor/alunos/<int:aluno_id>/avaliacoes", methods=["POST"])
@login_obrigatorio("instrutor")
def avaliacao_nova(user, aluno_id):
    _aluno_do_instrutor(aluno_id, user["id"])
    f = request.form
    erros = []
    d, erro = _data(f.get("data"), obrigatoria=True)
    if erro:
        erros.append(f"Data {erro}.")
    elif d > date.today():
        erros.append("A data da avaliação não pode ser no futuro.")
    chave = f.get("distancia", "")
    if chave not in daniels.DISTANCIAS_AVALIACAO:
        erros.append("Escolha a distância.")
        dist = tempo = None
    elif chave == "cooper":  # teste de 12 minutos: informa a distância percorrida
        tempo = 720
        try:
            dist = treinos.ler_distancia(f.get("distancia_cooper"))
            if not dist or not 1000 <= dist <= 6000:
                raise ValueError
        except ValueError:
            dist = None
            erros.append("Teste de 12 minutos: informe a distância percorrida (ex.: 2800 ou 2,8 km).")
    else:
        dist = daniels.DISTANCIAS_AVALIACAO[chave][1]
        tempo = treinos.ler_duracao(f.get("tempo"))
        if not tempo:
            erros.append("Informe o tempo (ex.: 24:30 ou 1:35:20).")
    v = None
    if dist and tempo and not erros:
        v = daniels.vdot(dist, tempo)
        if not 20 <= v <= 90:
            erros.append(f"O tempo informado resulta em VDOT {v:.1f}, fora do esperado (20 a 90). Confira o tempo.")
    if erros:
        for e in erros:
            flash(e, "erro")
    else:
        tipo = "teste" if chave == "cooper" or f.get("tipo") == "teste" else "prova"
        db.execute("INSERT INTO avaliacoes (aluno_id, data, distancia_m, tempo_s, tipo, descricao, vdot) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (aluno_id, d.isoformat(), dist, tempo, tipo, (f.get("descricao") or "").strip() or None, round(v, 1)))
        flash(f"Avaliação registrada: VDOT {v:.1f}.".replace(".", ",", 1), "ok")
    return redirect(url_for("aluno_editar", aluno_id=aluno_id) + "#daniels")


@app.route("/instrutor/avaliacoes/<int:aval_id>/excluir", methods=["POST"])
@login_obrigatorio("instrutor")
def avaliacao_excluir(user, aval_id):
    aval = db.query_one("SELECT a.* FROM avaliacoes a JOIN usuarios u ON u.id = a.aluno_id "
                        "WHERE a.id = ? AND u.instrutor_id = ?", (aval_id, user["id"]))
    if not aval:
        abort(404)
    db.execute("DELETE FROM avaliacoes WHERE id = ?", (aval_id,))
    flash("Avaliação excluída.", "ok")
    return redirect(url_for("aluno_editar", aluno_id=aval["aluno_id"]) + "#daniels")


@app.route("/instrutor/alunos/<int:aluno_id>/redefinir-senha", methods=["POST"])
@login_obrigatorio("instrutor")
def aluno_redefinir_senha(user, aluno_id):
    aluno = _aluno_do_instrutor(aluno_id, user["id"])
    senha = gerar_senha()
    db.execute("UPDATE usuarios SET senha_hash = ?, trocar_senha = 1 WHERE id = ?",
               (generate_password_hash(senha), aluno_id))
    return render_template("aluno_acesso.html", nome=aluno["nome"], email=aluno["email"],
                           senha=senha, titulo="Senha redefinida")


@app.route("/instrutor/alunos/<int:aluno_id>/status", methods=["POST"])
@login_obrigatorio("instrutor")
def aluno_status(user, aluno_id):
    aluno = _aluno_do_instrutor(aluno_id, user["id"])
    novo = 0 if aluno["ativo"] else 1
    db.execute("UPDATE usuarios SET ativo = ? WHERE id = ?", (novo, aluno_id))
    flash(f"Aluno {'reativado' if novo else 'desativado'}: {aluno['nome']}.", "ok")
    return redirect(url_for("alunos", mostrar=request.form.get("mostrar", "ativos")))


# ---------------------------------------------------------------- macrociclos (professor)
def _macro_do_instrutor(macro_id, instrutor_id):
    macro = db.query_one(
        "SELECT m.*, u.nome AS aluno_nome FROM macrociclos m JOIN usuarios u ON u.id = m.aluno_id "
        "WHERE m.id = ? AND u.instrutor_id = ?", (macro_id, instrutor_id))
    if not macro:
        abort(404)
    return macro


def _fase_do_instrutor(fase_id, instrutor_id):
    fase = db.query_one(
        "SELECT f.* FROM fases f JOIN macrociclos m ON m.id = f.macrociclo_id "
        "JOIN usuarios u ON u.id = m.aluno_id WHERE f.id = ? AND u.instrutor_id = ?",
        (fase_id, instrutor_id))
    if not fase:
        abort(404)
    return fase


def _data(valor, obrigatoria=False):
    valor = (valor or "").strip()
    if not valor:
        return None, ("obrigatória" if obrigatoria else None)
    try:
        return date.fromisoformat(valor), None
    except ValueError:
        return None, "inválida"


def _validar_macro(form):
    dados = {
        "nome": form.get("nome", "").strip(),
        "competicao": form.get("competicao", "").strip() or None,
        "observacoes": form.get("observacoes", "").strip() or None,
    }
    erros = []
    if not dados["nome"]:
        erros.append("Informe o nome do macrociclo.")
    ini, e1 = _data(form.get("data_inicio"), obrigatoria=True)
    comp, e2 = _data(form.get("data_competicao"))
    if e1:
        erros.append(f"Data de início {e1}.")
    if e2:
        erros.append(f"Data da competição {e2}.")
    if ini and comp and comp <= ini:
        erros.append("A competição precisa ser depois da data de início.")
    if ini and comp and (comp - ini).days > 7 * 104:
        erros.append("O macrociclo pode ter no máximo 2 anos.")
    dados["data_inicio"] = ini.isoformat() if ini else None
    dados["data_competicao"] = comp.isoformat() if comp else None
    for campo, rotulo, maximo, tipo in (("ref_km_semana", "Referência de km/semana", 400, float),
                                        ("ref_series_semana", "Referência de séries/semana", 500, int)):
        txt = (form.get(campo) or "").strip().replace(",", ".")
        dados[campo] = None
        if txt:
            try:
                v = tipo(float(txt)) if tipo is int else float(txt)
                if not 0 < v <= maximo:
                    raise ValueError
                dados[campo] = v
            except ValueError:
                erros.append(f"{rotulo}: informe um número maior que zero (até {maximo}).")
    return dados, erros


def _fases_do_macro(macro_id):
    return db.query_all("SELECT * FROM fases WHERE macrociclo_id = ? ORDER BY modalidade, ordem", (macro_id,))


def _renumerar(t, macro_id, modalidade):
    ids = [r["id"] for r in db.query_all(
        "SELECT id FROM fases WHERE macrociclo_id = ? AND modalidade = ? ORDER BY ordem, id",
        (macro_id, modalidade))]
    for i, fid in enumerate(ids, 1):
        t.execute("UPDATE fases SET ordem = ? WHERE id = ?", (i, fid))


@app.route("/instrutor/alunos/<int:aluno_id>/ciclos/novo", methods=["GET", "POST"])
@login_obrigatorio("instrutor")
def macro_novo(user, aluno_id):
    aluno = _aluno_do_instrutor(aluno_id, user["id"])
    dados = {"data_inicio": date.today().isoformat(), "modelo_academia": True, "modelo_corrida": True}
    if request.method == "POST":
        dados, erros = _validar_macro(request.form)
        dados["modelo_academia"] = bool(request.form.get("modelo_academia"))
        dados["modelo_corrida"] = bool(request.form.get("modelo_corrida"))
        if erros:
            for e in erros:
                flash(e, "erro")
        else:
            ini = date.fromisoformat(dados["data_inicio"])
            comp = date.fromisoformat(dados["data_competicao"]) if dados["data_competicao"] else None
            with db.Transacao() as t:
                mid = t.insert(
                    "INSERT INTO macrociclos (aluno_id, nome, competicao, data_inicio, data_competicao, observacoes, "
                    "ref_km_semana, ref_series_semana) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (aluno_id, dados["nome"], dados["competicao"], dados["data_inicio"],
                     dados["data_competicao"], dados["observacoes"], dados["ref_km_semana"], dados["ref_series_semana"]))
                for mod in ciclos.MODALIDADES:
                    if dados[f"modelo_{mod}"]:
                        for f in ciclos.fases_modelo(mod, ini, comp):
                            _inserir_fase(t, mid, mod, f)
            flash("Macrociclo criado.", "ok")
            return redirect(url_for("macro_ver", macro_id=mid))
    return render_template("macro_form.html", aluno=aluno, macro=dados, novo=True)


def _inserir_fase(t, macro_id, modalidade, f):
    t.insert(
        "INSERT INTO fases (macrociclo_id, modalidade, ordem, nome, objetivo, semanas, series, repeticoes, "
        "intensidade, volume, intensidade_ref, volume_ref, conteudo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (macro_id, modalidade, f["ordem"], f["nome"], f.get("objetivo"), f["semanas"], f.get("series"),
         f.get("repeticoes"), f["intensidade"], f["volume"], f.get("intensidade_ref"), f.get("volume_ref"),
         f.get("conteudo")))


def _visao_com_totais(macro):
    """Visão do macrociclo + volume planejado (treinos montados) por fase e no total."""
    visao = ciclos.montar(macro, _fases_do_macro(macro["id"]))
    limite = _limite_semanas(macro, visao)
    fim = treinos.inicio_semana(visao["inicio"], limite) + timedelta(days=6)
    por_dia = treinos.carregar(macro["id"], visao["inicio"], fim)
    todos = [t for dia in por_dia.values() for t in dia]
    visao["totais"], visao["plan"] = {}, {}
    aluno = db.query_one("SELECT * FROM usuarios WHERE id = ?", (macro["aluno_id"],))
    perfil = perfil_corrida(aluno)
    visao["perfil"] = perfil
    metricas = treinos.metricas_semanais(todos, visao["inicio"], perfil["paces"])
    referencias = {"corrida": macro.get("ref_km_semana") or (perfil["faixa"]["max"] if perfil["faixa"] else None),
                   "academia": macro.get("ref_series_semana")}
    visao["ref_fonte"] = {"corrida": "macro" if macro.get("ref_km_semana") else ("faixa" if perfil["faixa"] else None),
                          "academia": "macro" if macro.get("ref_series_semana") else None}
    for mod, grupo in visao["grupos"].items():
        plan = ciclos.niveis_planejados(metricas[mod], mod, referencias[mod])
        acima = ciclos.excessos(grupo, plan)
        visao["plan"][mod] = plan
        if grupo:
            visao["graficos"][mod] = ciclos.grafico(grupo, visao["total_semanas"], visao["inicio"], plan, acima)
    for mod, grupo in visao["grupos"].items():
        do_mod = [t for t in todos if t["modalidade"] == mod]
        for f in grupo:
            ini, fim_f = f["inicio"].isoformat(), f["fim"].isoformat()
            na_fase = [t for t in do_mod if ini <= t["data"] <= fim_f]
            f["plan"] = treinos.somar(t["vol"] for t in na_fase)
            semanas_montadas = {treinos.semana_de(visao["inicio"], date.fromisoformat(t["data"])) for t in na_fase}
            f["plan"]["semanas"] = len(semanas_montadas)
            f["plan"]["por_semana"] = f["plan"]["metros"] / len(semanas_montadas) if semanas_montadas else 0
        visao["totais"][mod] = treinos.somar(t["vol"] for t in do_mod)
    visao["semanas_com_treino"] = len({treinos.semana_de(visao["inicio"], date.fromisoformat(t["data"])) for t in todos})
    return visao


@app.route("/instrutor/ciclos/<int:macro_id>")
@login_obrigatorio("instrutor")
def macro_ver(user, macro_id):
    macro = _macro_do_instrutor(macro_id, user["id"])
    return render_template("macro_ver.html", macro=macro, v=_visao_com_totais(macro), editavel=True)


@app.route("/instrutor/ciclos/<int:macro_id>/editar", methods=["GET", "POST"])
@login_obrigatorio("instrutor")
def macro_editar(user, macro_id):
    macro = _macro_do_instrutor(macro_id, user["id"])
    aluno = _aluno_do_instrutor(macro["aluno_id"], user["id"])
    if request.method == "POST":
        dados, erros = _validar_macro(request.form)
        if erros:
            for e in erros:
                flash(e, "erro")
            macro.update(dados)
        else:
            db.execute("UPDATE macrociclos SET nome = ?, competicao = ?, data_inicio = ?, data_competicao = ?, "
                       "observacoes = ?, ref_km_semana = ?, ref_series_semana = ? WHERE id = ?",
                       (dados["nome"], dados["competicao"], dados["data_inicio"], dados["data_competicao"],
                        dados["observacoes"], dados["ref_km_semana"], dados["ref_series_semana"], macro_id))
            flash("Macrociclo salvo.", "ok")
            return redirect(url_for("macro_ver", macro_id=macro_id))
    return render_template("macro_form.html", aluno=aluno, macro=macro, novo=False)


@app.route("/instrutor/ciclos/<int:macro_id>/excluir", methods=["POST"])
@login_obrigatorio("instrutor")
def macro_excluir(user, macro_id):
    macro = _macro_do_instrutor(macro_id, user["id"])
    with db.Transacao() as t:
        t.execute("DELETE FROM fases WHERE macrociclo_id = ?", (macro_id,))
        t.execute("DELETE FROM macrociclos WHERE id = ?", (macro_id,))
    flash(f"Macrociclo “{macro['nome']}” excluído.", "ok")
    return redirect(url_for("aluno_editar", aluno_id=macro["aluno_id"]))


def _validar_fase(form):
    dados = {k: form.get(k, "").strip() or None for k in
             ("nome", "objetivo", "series", "repeticoes", "intensidade_ref", "volume_ref", "conteudo")}
    erros = []
    if not dados["nome"]:
        erros.append("Informe o nome da fase.")
    for campo, minimo, maximo, rotulo in (("semanas", 1, 104, "Semanas"),
                                          ("intensidade", 1, 5, "Intensidade"), ("volume", 1, 5, "Volume")):
        try:
            v = int(form.get(campo, ""))
            if not minimo <= v <= maximo:
                raise ValueError
            dados[campo] = v
        except ValueError:
            dados[campo] = None
            erros.append(f"{rotulo}: informe um número de {minimo} a {maximo}.")
    return dados, erros


@app.route("/instrutor/ciclos/<int:macro_id>/fases/nova", methods=["GET", "POST"])
@login_obrigatorio("instrutor")
def fase_nova(user, macro_id):
    macro = _macro_do_instrutor(macro_id, user["id"])
    modalidade = request.values.get("modalidade", "")
    if modalidade not in ciclos.MODALIDADES:
        abort(404)
    fase = {"modalidade": modalidade, "semanas": 4, "intensidade": 3, "volume": 3}
    if request.method == "POST":
        fase, erros = _validar_fase(request.form)
        fase["modalidade"] = modalidade
        if erros:
            for e in erros:
                flash(e, "erro")
        else:
            ultima = db.query_one("SELECT MAX(ordem) AS m FROM fases WHERE macrociclo_id = ? AND modalidade = ?",
                                  (macro_id, modalidade))["m"] or 0
            with db.Transacao() as t:
                _inserir_fase(t, macro_id, modalidade, {**fase, "ordem": ultima + 1})
            flash("Fase adicionada.", "ok")
            return redirect(url_for("macro_ver", macro_id=macro_id) + f"#{modalidade}")
    return render_template("fase_form.html", macro=macro, fase=fase, nova=True, c=ciclos)


@app.route("/instrutor/fases/<int:fase_id>", methods=["GET", "POST"])
@login_obrigatorio("instrutor")
def fase_editar(user, fase_id):
    fase = _fase_do_instrutor(fase_id, user["id"])
    macro = _macro_do_instrutor(fase["macrociclo_id"], user["id"])
    if request.method == "POST":
        dados, erros = _validar_fase(request.form)
        if erros:
            for e in erros:
                flash(e, "erro")
            fase.update(dados)
        else:
            db.execute("UPDATE fases SET nome = ?, objetivo = ?, semanas = ?, series = ?, repeticoes = ?, "
                       "intensidade = ?, volume = ?, intensidade_ref = ?, volume_ref = ?, conteudo = ? WHERE id = ?",
                       (dados["nome"], dados["objetivo"], dados["semanas"], dados["series"], dados["repeticoes"],
                        dados["intensidade"], dados["volume"], dados["intensidade_ref"], dados["volume_ref"],
                        dados["conteudo"], fase_id))
            flash("Fase salva.", "ok")
            return redirect(url_for("macro_ver", macro_id=macro["id"]) + f"#{fase['modalidade']}")
    return render_template("fase_form.html", macro=macro, fase=fase, nova=False, c=ciclos)


@app.route("/instrutor/fases/<int:fase_id>/excluir", methods=["POST"])
@login_obrigatorio("instrutor")
def fase_excluir(user, fase_id):
    fase = _fase_do_instrutor(fase_id, user["id"])
    with db.Transacao() as t:
        t.execute("DELETE FROM fases WHERE id = ?", (fase_id,))
    with db.Transacao() as t:
        _renumerar(t, fase["macrociclo_id"], fase["modalidade"])
    flash(f"Fase “{fase['nome']}” excluída.", "ok")
    return redirect(url_for("macro_ver", macro_id=fase["macrociclo_id"]) + f"#{fase['modalidade']}")


@app.route("/instrutor/fases/<int:fase_id>/mover", methods=["POST"])
@login_obrigatorio("instrutor")
def fase_mover(user, fase_id):
    fase = _fase_do_instrutor(fase_id, user["id"])
    passo = -1 if request.form.get("direcao") == "acima" else 1
    vizinha = db.query_one(
        "SELECT id, ordem FROM fases WHERE macrociclo_id = ? AND modalidade = ? AND ordem = ?",
        (fase["macrociclo_id"], fase["modalidade"], fase["ordem"] + passo))
    if vizinha:
        with db.Transacao() as t:
            t.execute("UPDATE fases SET ordem = ? WHERE id = ?", (fase["ordem"], vizinha["id"]))
            t.execute("UPDATE fases SET ordem = ? WHERE id = ?", (vizinha["ordem"], fase_id))
    return redirect(url_for("macro_ver", macro_id=fase["macrociclo_id"]) + f"#{fase['modalidade']}")


# ---------------------------------------------------------------- treinos (professor)
def _limite_semanas(macro, visao):
    """Quantas semanas o macrociclo comporta para treinos."""
    limite = visao["total_semanas"]
    if macro.get("data_competicao"):
        limite = max(limite, ciclos.semanas_ate(visao["inicio"], visao["competicao"]) + ciclos.SEMANAS_TRANSICAO)
    return max(1, limite)


def _semana_atual(visao, limite):
    hoje = date.today()
    return min(max(1, treinos.semana_de(visao["inicio"], hoje)), limite)


def _primeiro_numero(texto):
    m = re.search(r"\d+", texto or "")
    return int(m.group()) if m else None


def _montar_semana(macro, n):
    visao = ciclos.montar(macro, _fases_do_macro(macro["id"]))
    limite = _limite_semanas(macro, visao)
    if not 1 <= n <= limite:
        abort(404)
    ini = treinos.inicio_semana(visao["inicio"], n)
    por_dia = treinos.carregar(macro["id"], ini, ini + timedelta(days=6))
    dias = []
    for i in range(7):
        d = ini + timedelta(days=i)
        dias.append({"data": d, "nome": treinos.DIAS[d.weekday()], "curto": treinos.DIAS_CURTOS[d.weekday()],
                     "treinos": por_dia.get(d.isoformat(), []), "hoje": d == date.today(),
                     "data_mais7": d + timedelta(days=7)})
    todos = [t for d in dias for t in d["treinos"]]
    fases_semana = {}
    for mod, grupo in visao["grupos"].items():
        fases_semana[mod] = next((f for f in grupo if f["inicio"] <= ini + timedelta(days=3) <= f["fim"]), None)
    resumo = {mod: treinos.somar(t["vol"] for t in todos if t["modalidade"] == mod) for mod in ciclos.MODALIDADES}
    aluno = db.query_one("SELECT * FROM usuarios WHERE id = ?", (macro["aluno_id"],))
    perfil = perfil_corrida(aluno)
    met = treinos.metricas_semanais([t for t in todos if t["modalidade"] == "corrida"], ini, perfil["paces"])
    zonas = met["corrida"].get(1)  # semana 1 relativa ao início desta semana
    for d in dias:  # zona de cada bloco, para exibir
        for t in d["treinos"]:
            if t["modalidade"] == "corrida":
                for b in t["itens"]:
                    b["zona_calc"] = treinos.zona_do_bloco(b, perfil["paces"])
                    b["pace_s"] = treinos.ler_pace(b.get("pace"))
    return {"n": n, "limite": limite, "inicio": ini, "fim": ini + timedelta(days=6), "dias": dias,
            "fases": fases_semana, "resumo": resumo, "visao": visao, "zonas": zonas, "perfil": perfil}


def _treino_do_instrutor(treino_id, instrutor_id):
    t = db.query_one(
        "SELECT t.id FROM treinos t JOIN macrociclos m ON m.id = t.macrociclo_id "
        "JOIN usuarios u ON u.id = m.aluno_id WHERE t.id = ? AND u.instrutor_id = ?", (treino_id, instrutor_id))
    if not t:
        abort(404)
    return treinos.um(treino_id)


@app.route("/instrutor/ciclos/<int:macro_id>/semanas")
@login_obrigatorio("instrutor")
def semanas(user, macro_id):
    macro = _macro_do_instrutor(macro_id, user["id"])
    visao = ciclos.montar(macro, _fases_do_macro(macro_id))
    return redirect(url_for("semana", macro_id=macro_id, n=_semana_atual(visao, _limite_semanas(macro, visao))))


@app.route("/instrutor/ciclos/<int:macro_id>/semanas/<int:n>")
@login_obrigatorio("instrutor")
def semana(user, macro_id, n):
    macro = _macro_do_instrutor(macro_id, user["id"])
    return render_template("semana.html", macro=macro, s=_montar_semana(macro, n), editavel=True,
                           fmt_dist=treinos.fmt_distancia, d_=daniels)


def _data_no_macro(macro, texto):
    """Valida que a data está dentro das semanas do macrociclo."""
    visao = ciclos.montar(macro, _fases_do_macro(macro["id"]))
    limite = _limite_semanas(macro, visao)
    d, erro = _data(texto, obrigatoria=True)
    if erro:
        return None, f"Data {erro}."
    if not 1 <= treinos.semana_de(visao["inicio"], d) <= limite or d < visao["inicio"]:
        fim = treinos.inicio_semana(visao["inicio"], limite) + timedelta(days=6)
        return None, f"A data precisa estar entre {visao['inicio']:%d/%m/%Y} e {fim:%d/%m/%Y}."
    return d, None


@app.route("/instrutor/ciclos/<int:macro_id>/treinos/novo", methods=["GET", "POST"])
@login_obrigatorio("instrutor")
def treino_novo(user, macro_id):
    macro = _macro_do_instrutor(macro_id, user["id"])
    modalidade = request.values.get("modalidade", "")
    if modalidade not in ciclos.MODALIDADES:
        abort(404)
    if request.method == "POST":
        dados, itens, erros = treinos.ler_form(request.form, modalidade)
        d, erro = _data_no_macro(macro, dados["data"])
        if erro:
            erros.insert(0, erro)
        if not erros:
            with db.Transacao() as t:
                tid = t.insert("INSERT INTO treinos (macrociclo_id, data, modalidade, titulo, observacoes) "
                               "VALUES (?, ?, ?, ?, ?)", (macro_id, d.isoformat(), modalidade,
                                                          dados["titulo"], dados["observacoes"]))
                treinos.salvar(t, tid, modalidade, itens)
            flash("Treino salvo.", "ok")
            return _voltar_semana(macro, d)
        for e in erros:
            flash(e, "erro")
        treino = {**dados, "modalidade": modalidade, "itens": itens}
    else:
        d, _ = _data_no_macro(macro, request.args.get("data"))
        d = d or ciclos.montar(macro, _fases_do_macro(macro_id))["inicio"]
        treino = {"data": d.isoformat(), "modalidade": modalidade, "itens": []}
    return _form_treino(user, macro, treino, novo=True)


def _voltar_semana(macro, d):
    ini = date.fromisoformat(macro["data_inicio"])
    return redirect(url_for("semana", macro_id=macro["id"], n=treinos.semana_de(ini, d)) + f"#d{d.isoformat()}")


def _form_treino(user, macro, treino, novo):
    visao = ciclos.montar(macro, _fases_do_macro(macro["id"]))
    try:
        d = date.fromisoformat(treino["data"])
    except (TypeError, ValueError):
        d = visao["inicio"]
    fase = next((f for f in visao["grupos"][treino["modalidade"]] if f["inicio"] <= d <= f["fim"]), None)
    sugestao = {"series": _primeiro_numero(fase and fase.get("series")) or 3,
                "repeticoes": (fase and fase.get("repeticoes")) or ""}
    if not treino["itens"]:
        treino["itens"] = [{"series": sugestao["series"], "repeticoes": sugestao["repeticoes"]}] if \
            treino["modalidade"] == "academia" else [{"tipo": "", "repeticoes": 1, "zona": ""}]
    for it in treino["itens"]:
        if "distancia_m" in it and "distancia" not in it:
            it["distancia"] = treinos.fmt_distancia(it["distancia_m"])
    n = min(max(1, treinos.semana_de(visao["inicio"], d)), _limite_semanas(macro, visao))
    voltar = url_for("semana", macro_id=macro["id"], n=n) + f"#d{d.isoformat()}"
    aluno = db.query_one("SELECT * FROM usuarios WHERE id = ?", (macro["aluno_id"],))
    return render_template("treino_form.html", macro=macro, treino=treino, novo=novo, fase=fase, voltar=voltar,
                           perfil=perfil_corrida(aluno), d=daniels,
                           sugestao=sugestao, tipos=treinos.TIPOS_CORRIDA,
                           exercicios=treinos.exercicios_usados(user["id"]),
                           dia_nome=treinos.DIAS[d.weekday()])


@app.route("/instrutor/treinos/<int:treino_id>", methods=["GET", "POST"])
@login_obrigatorio("instrutor")
def treino_editar(user, treino_id):
    treino = _treino_do_instrutor(treino_id, user["id"])
    macro = _macro_do_instrutor(treino["macrociclo_id"], user["id"])
    if request.method == "POST":
        dados, itens, erros = treinos.ler_form(request.form, treino["modalidade"])
        d, erro = _data_no_macro(macro, dados["data"])
        if erro:
            erros.insert(0, erro)
        validos = {i["id"] for i in treino["itens"]}
        for it in itens:  # id de item de outro treino é ignorado (vira item novo)
            if it["id"] not in validos:
                it["id"] = None
        if not erros:
            with db.Transacao() as t:
                t.execute("UPDATE treinos SET data = ?, titulo = ?, observacoes = ? WHERE id = ?",
                          (d.isoformat(), dados["titulo"], dados["observacoes"], treino_id))
                treinos.salvar(t, treino_id, treino["modalidade"], itens)
            flash("Treino salvo.", "ok")
            return _voltar_semana(macro, d)
        for e in erros:
            flash(e, "erro")
        treino.update(dados)
        treino["itens"] = itens
    return _form_treino(user, macro, treino, novo=False)


@app.route("/instrutor/treinos/<int:treino_id>/excluir", methods=["POST"])
@login_obrigatorio("instrutor")
def treino_excluir(user, treino_id):
    treino = _treino_do_instrutor(treino_id, user["id"])
    macro = _macro_do_instrutor(treino["macrociclo_id"], user["id"])
    with db.Transacao() as t:
        for tabela in ("treino_academia", "treino_corrida"):
            t.execute(f"DELETE FROM {tabela} WHERE treino_id = ?", (treino_id,))
        t.execute("DELETE FROM treinos WHERE id = ?", (treino_id,))
    flash("Treino excluído.", "ok")
    return _voltar_semana(macro, date.fromisoformat(treino["data"]))


@app.route("/instrutor/treinos/<int:treino_id>/duplicar", methods=["POST"])
@login_obrigatorio("instrutor")
def treino_duplicar(user, treino_id):
    treino = _treino_do_instrutor(treino_id, user["id"])
    macro = _macro_do_instrutor(treino["macrociclo_id"], user["id"])
    d, erro = _data_no_macro(macro, request.form.get("data"))
    if erro:
        flash(erro, "erro")
        return _voltar_semana(macro, date.fromisoformat(treino["data"]))
    with db.Transacao() as t:
        treinos.copiar(t, treino, d)
    flash(f"Treino copiado para {treinos.DIAS[d.weekday()].lower()}, {d:%d/%m}.", "ok")
    return _voltar_semana(macro, d)


@app.route("/instrutor/ciclos/<int:macro_id>/semanas/<int:n>/copiar", methods=["POST"])
@login_obrigatorio("instrutor")
def semana_copiar(user, macro_id, n):
    macro = _macro_do_instrutor(macro_id, user["id"])
    origem = _montar_semana(macro, n)
    try:
        destino = int(request.form.get("destino", ""))
    except ValueError:
        destino = 0
    if not 1 <= destino <= origem["limite"] or destino == n:
        flash("Escolha uma semana de destino válida.", "erro")
        return redirect(url_for("semana", macro_id=macro_id, n=n))
    desloc = timedelta(weeks=destino - n)
    copiados = 0
    with db.Transacao() as t:
        for dia in origem["dias"]:
            for tr in dia["treinos"]:
                treinos.copiar(t, tr, dia["data"] + desloc)
                copiados += 1
    if copiados:
        flash(f"{copiados} treino{'s' if copiados != 1 else ''} copiado{'s' if copiados != 1 else ''} "
              f"da semana {n} para a semana {destino}.", "ok")
    else:
        flash("A semana não tem treinos para copiar.", "erro")
    return redirect(url_for("semana", macro_id=macro_id, n=destino if copiados else n))


# ---------------------------------------------------------------- aluno
def _macro_vigente(aluno_id, hoje=None):
    """Macrociclo em andamento; senão o próximo a começar; senão o mais recente."""
    hoje = hoje or date.today()
    macros = db.query_all("SELECT * FROM macrociclos WHERE aluno_id = ? ORDER BY data_inicio DESC", (aluno_id,))
    andamento, futuros = None, []
    for m in macros:
        v = ciclos.montar(m, _fases_do_macro(m["id"]), hoje)
        if v["inicio"] <= hoje <= v["fim"]:
            andamento = andamento or (m, v)
        elif v["inicio"] > hoje:
            futuros.append((m, v))
    if andamento:
        return andamento, macros
    if futuros:
        return futuros[-1], macros
    if macros:
        return (macros[0], ciclos.montar(macros[0], _fases_do_macro(macros[0]["id"]), hoje)), macros
    return (None, None), macros


@app.route("/aluno")
@login_obrigatorio("aluno")
def painel_aluno(user):
    (macro, visao), macros = _macro_vigente(user["id"])
    if macro:
        visao = _visao_com_totais(macro)
    aluno = db.query_one("SELECT * FROM usuarios WHERE id = ?", (user["id"],))
    return render_template("painel_aluno.html", macro=macro, v=visao, macros=macros,
                           perfil=perfil_corrida(aluno), d=daniels)


@app.route("/aluno/semana")
@login_obrigatorio("aluno")
def aluno_semana_atual(user):
    (macro, visao), _ = _macro_vigente(user["id"])
    if not macro:
        return redirect(url_for("painel_aluno"))
    return redirect(url_for("aluno_semana", macro_id=macro["id"],
                            n=_semana_atual(visao, _limite_semanas(macro, visao))))


@app.route("/aluno/ciclos/<int:macro_id>/semanas")
@login_obrigatorio("aluno")
def aluno_semanas(user, macro_id):
    macro = db.query_one("SELECT * FROM macrociclos WHERE id = ? AND aluno_id = ?", (macro_id, user["id"]))
    if not macro:
        abort(404)
    visao = ciclos.montar(macro, _fases_do_macro(macro_id))
    return redirect(url_for("aluno_semana", macro_id=macro_id, n=_semana_atual(visao, _limite_semanas(macro, visao))))


@app.route("/aluno/ciclos/<int:macro_id>/semanas/<int:n>")
@login_obrigatorio("aluno")
def aluno_semana(user, macro_id, n):
    macro = db.query_one("SELECT * FROM macrociclos WHERE id = ? AND aluno_id = ?", (macro_id, user["id"]))
    if not macro:
        abort(404)
    return render_template("semana.html", macro=macro, s=_montar_semana(macro, n), editavel=False,
                           fmt_dist=treinos.fmt_distancia, d_=daniels)


@app.route("/aluno/ciclos/<int:macro_id>")
@login_obrigatorio("aluno")
def aluno_macro(user, macro_id):
    macro = db.query_one("SELECT * FROM macrociclos WHERE id = ? AND aluno_id = ?", (macro_id, user["id"]))
    if not macro:
        abort(404)
    return render_template("macro_ver.html", macro=macro, v=_visao_com_totais(macro), editavel=False)


# ---------------------------------------------------------------- erros
@app.errorhandler(403)
def proibido(_):
    return render_template("erro.html", titulo="Acesso negado",
                           msg="Esta área não é do seu perfil."), 403


@app.errorhandler(404)
def nao_encontrado(_):
    return render_template("erro.html", titulo="Não encontrado",
                           msg="A página ou o registro não existe."), 404


# ---------------------------------------------------------------- comandos
@app.cli.command("criar-usuario")
@click.option("--nome", prompt=True)
@click.option("--email", prompt=True)
@click.option("--perfil", type=click.Choice(["instrutor", "aluno"]), prompt=True)
@click.password_option("--senha")
def criar_usuario(nome, email, perfil, senha):
    """Cria um usuário (use para o primeiro instrutor)."""
    email = email.strip().lower()
    if db.query_one("SELECT id FROM usuarios WHERE email = ?", (email,)):
        raise click.ClickException("Já existe usuário com esse e-mail.")
    db.execute("INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES (?, ?, ?, ?)",
               (nome.strip(), email, generate_password_hash(senha), perfil))
    click.echo(f"Usuário {email} ({perfil}) criado.")


if __name__ == "__main__":
    app.run(debug=True)
