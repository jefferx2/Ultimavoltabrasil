"""Área do administrador: cadastro de outros professores."""
from flask import abort, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

import db
from app import EMAIL_RE, SENHA_MIN, admin_obrigatorio, app, gerar_senha


def _professor(prof_id):
    p = db.query_one("SELECT * FROM usuarios WHERE id = ? AND perfil = 'instrutor'", (prof_id,))
    if not p:
        abort(404)
    return p


def _validar(form, prof_id=None):
    dados = {"nome": form.get("nome", "").strip(), "email": form.get("email", "").strip().lower(),
             "telefone": form.get("telefone", "").strip() or None, "admin": 1 if form.get("admin") else 0}
    erros = []
    if not dados["nome"]:
        erros.append("Informe o nome.")
    if not EMAIL_RE.match(dados["email"]):
        erros.append("Informe um e-mail válido.")
    else:
        outro = db.query_one("SELECT id FROM usuarios WHERE email = ?", (dados["email"],))
        if outro and outro["id"] != prof_id:
            erros.append("Já existe um usuário com esse e-mail.")
    return dados, erros


@app.route("/instrutor/professores")
@admin_obrigatorio
def professores(user):
    lista = db.query_all(
        "SELECT p.*, (SELECT COUNT(*) FROM usuarios a WHERE a.instrutor_id = p.id AND a.perfil = 'aluno' AND a.ativo = 1) "
        "AS alunos FROM usuarios p WHERE p.perfil = 'instrutor' ORDER BY p.ativo DESC, p.nome")
    return render_template("professores.html", professores=lista)


@app.route("/instrutor/professores/novo", methods=["GET", "POST"])
@admin_obrigatorio
def professor_novo(user):
    dados = {}
    if request.method == "POST":
        dados, erros = _validar(request.form)
        senha = request.form.get("senha", "").strip() or gerar_senha()
        if len(senha) < SENHA_MIN:
            erros.append(f"A senha inicial precisa ter pelo menos {SENHA_MIN} caracteres.")
        if erros:
            for e in erros:
                flash(e, "erro")
        else:
            db.execute("INSERT INTO usuarios (nome, email, senha_hash, perfil, telefone, admin, trocar_senha) "
                       "VALUES (?, ?, ?, 'instrutor', ?, ?, 1)",
                       (dados["nome"], dados["email"], generate_password_hash(senha), dados["telefone"], dados["admin"]))
            return render_template("aluno_acesso.html", nome=dados["nome"], email=dados["email"], senha=senha,
                                   titulo="Professor cadastrado", voltar=url_for("professores"),
                                   voltar_txt="Voltar aos professores")
    return render_template("professor_form.html", prof=dados, novo=True, senha_min=SENHA_MIN)


@app.route("/instrutor/professores/<int:prof_id>", methods=["GET", "POST"])
@admin_obrigatorio
def professor_editar(user, prof_id):
    prof = _professor(prof_id)
    if request.method == "POST":
        dados, erros = _validar(request.form, prof_id)
        if prof_id == user["id"] and not dados["admin"]:
            erros.append("Você não pode tirar o seu próprio acesso de administrador.")
        if erros:
            for e in erros:
                flash(e, "erro")
            prof.update(dados)
        else:
            db.execute("UPDATE usuarios SET nome = ?, email = ?, telefone = ?, admin = ? WHERE id = ?",
                       (dados["nome"], dados["email"], dados["telefone"], dados["admin"], prof_id))
            flash("Dados do professor salvos.", "ok")
            return redirect(url_for("professores"))
    alunos = db.query_all("SELECT id, nome, ativo FROM usuarios WHERE instrutor_id = ? AND perfil = 'aluno' ORDER BY nome",
                          (prof_id,))
    return render_template("professor_form.html", prof=prof, novo=False, senha_min=SENHA_MIN, alunos=alunos,
                           eu=prof_id == user["id"])


@app.route("/instrutor/professores/<int:prof_id>/redefinir-senha", methods=["POST"])
@admin_obrigatorio
def professor_redefinir_senha(user, prof_id):
    prof = _professor(prof_id)
    if prof_id == user["id"]:
        flash("Para trocar a sua própria senha, use “Trocar senha” no seu nome, no topo.", "erro")
        return redirect(url_for("professor_editar", prof_id=prof_id))
    senha = gerar_senha()
    db.execute("UPDATE usuarios SET senha_hash = ?, trocar_senha = 1 WHERE id = ?", (generate_password_hash(senha), prof_id))
    return render_template("aluno_acesso.html", nome=prof["nome"], email=prof["email"], senha=senha,
                           titulo="Senha redefinida", voltar=url_for("professores"), voltar_txt="Voltar aos professores")


@app.route("/instrutor/professores/<int:prof_id>/status", methods=["POST"])
@admin_obrigatorio
def professor_status(user, prof_id):
    prof = _professor(prof_id)
    if prof_id == user["id"]:
        flash("Você não pode desativar o seu próprio acesso.", "erro")
        return redirect(url_for("professor_editar", prof_id=prof_id))
    novo = 0 if prof["ativo"] else 1
    db.execute("UPDATE usuarios SET ativo = ? WHERE id = ?", (novo, prof_id))
    flash(f"Professor {'reativado' if novo else 'desativado'}: {prof['nome']}.", "ok")
    return redirect(url_for("professores"))


@app.route("/instrutor/professores/<int:prof_id>/transferir", methods=["POST"])
@admin_obrigatorio
def professor_transferir(user, prof_id):
    """Passa todos os alunos deste professor para outro (ex.: antes de desativá-lo)."""
    _professor(prof_id)
    try:
        destino = int(request.form.get("destino", ""))
    except ValueError:
        destino = 0
    alvo = db.query_one("SELECT id, nome FROM usuarios WHERE id = ? AND perfil = 'instrutor' AND ativo = 1", (destino,))
    if not alvo or destino == prof_id:
        flash("Escolha um professor ativo para receber os alunos.", "erro")
    else:
        n = db.query_one("SELECT COUNT(*) AS n FROM usuarios WHERE instrutor_id = ? AND perfil = 'aluno'", (prof_id,))["n"]
        db.execute("UPDATE usuarios SET instrutor_id = ? WHERE instrutor_id = ? AND perfil = 'aluno'", (destino, prof_id))
        flash(f"{n} aluno{'s' if n != 1 else ''} transferido{'s' if n != 1 else ''} para {alvo['nome']}.", "ok")
    return redirect(url_for("professor_editar", prof_id=prof_id))


@app.context_processor
def _outros_professores():
    def outros(exceto):
        return db.query_all("SELECT id, nome FROM usuarios WHERE perfil = 'instrutor' AND ativo = 1 AND id <> ? ORDER BY nome",
                            (exceto,))
    return {"outros_professores": outros}
