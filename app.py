"""Última Volta Brasil — sistema de treinos (instrutor / aluno)."""
import os
import secrets
from functools import wraps

import click
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV") == "production"

db.init_db()


# ---------------------------------------------------------------- utilidades
def usuario_atual():
    uid = session.get("uid")
    if not uid:
        return None
    return db.query_one("SELECT id, nome, email, perfil FROM usuarios WHERE id = ? AND ativo = 1", (uid,))


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


@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get("csrf")
        if not token or token != request.form.get("csrf"):
            abort(400)


@app.context_processor
def injetar():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return {"csrf_token": session["csrf"], "usuario": usuario_atual()}


# ---------------------------------------------------------------- rotas
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
            nxt = request.args.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(destino_por_perfil(row["perfil"]))
        flash("E-mail ou senha incorretos.")
    return render_template("login.html")


@app.route("/sair")
def sair():
    session.clear()
    return redirect(url_for("home"))


@app.route("/instrutor")
@login_obrigatorio("instrutor")
def painel_instrutor(user):
    return render_template("painel_instrutor.html")


@app.route("/aluno")
@login_obrigatorio("aluno")
def painel_aluno(user):
    return render_template("painel_aluno.html")


@app.errorhandler(403)
def proibido(_):
    return render_template("erro.html", titulo="Acesso negado",
                           msg="Esta área não é do seu perfil."), 403


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
