"""Última Volta Brasil — sistema de treinos (instrutor / aluno)."""
import os
import re
import secrets
from datetime import date
from functools import wraps

import click
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db

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
    return {"csrf_token": session["csrf"], "usuario": usuario_atual()}


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
    return render_template("painel_instrutor.html", total_alunos=total)


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
    }
    erros = []
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
                "prova_principal, telefone, observacoes, trocar_senha) "
                "VALUES (?, ?, ?, 'aluno', ?, ?, ?, ?, ?, 1)",
                (dados["nome"], dados["email"], generate_password_hash(senha), user["id"],
                 dados["data_nascimento"], dados["prova_principal"], dados["telefone"], dados["observacoes"]))
            return render_template("aluno_acesso.html", nome=dados["nome"], email=dados["email"],
                                   senha=senha, titulo="Aluno cadastrado")
    return render_template("aluno_form.html", aluno=dados, novo=True, provas=PROVAS_SUGERIDAS, senha_min=SENHA_MIN)


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
                "telefone = ?, observacoes = ? WHERE id = ?",
                (dados["nome"], dados["email"], dados["data_nascimento"], dados["prova_principal"],
                 dados["telefone"], dados["observacoes"], aluno_id))
            flash("Dados do aluno salvos.", "ok")
            return redirect(url_for("alunos"))
    return render_template("aluno_form.html", aluno=aluno, novo=False, provas=PROVAS_SUGERIDAS, senha_min=SENHA_MIN)


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


# ---------------------------------------------------------------- aluno
@app.route("/aluno")
@login_obrigatorio("aluno")
def painel_aluno(user):
    return render_template("painel_aluno.html")


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
