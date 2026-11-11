"""Área do administrador: cadastro de outros professores."""
from flask import abort, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

import db
import vinculos
from app import EMAIL_RE, SENHA_MIN, admin_obrigatorio, app, gerar_senha
from vinculos import params_acesso, sql_acesso


def _todos_alunos():
    """Alunos ativos do sistema, com os professores de cada um (para o administrador escolher)."""
    alunos = db.query_all("SELECT id, nome, email FROM usuarios WHERE perfil = 'aluno' AND ativo = 1 ORDER BY nome")
    for a in alunos:
        a["professores"] = vinculos.professores_do_aluno(a["id"])
    return alunos


def _aplicar_alunos(prof_id, form):
    """Vincula ou transfere os alunos marcados no formulário. Devolve a mensagem do resultado."""
    ids = [int(x) for x in form.getlist("aluno_ids") if x.isdigit()]
    validos = {a["id"] for a in db.query_all("SELECT id FROM usuarios WHERE perfil = 'aluno'")}
    ids = [i for i in ids if i in validos]
    if not ids:
        return None
    modo = form.get("modo")
    for aid in ids:
        if modo == "transferir":
            vinculos.transferir(aid, prof_id)
        else:
            vinculos.vincular(aid, prof_id)
    n = len(ids)
    return (f"{n} aluno{'s' if n != 1 else ''} " +
            ("transferido" + ("s" if n != 1 else "") if modo == "transferir" else "vinculado" + ("s" if n != 1 else "")) + ".")


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
        "SELECT p.*, (SELECT COUNT(*) FROM usuarios a WHERE a.perfil = 'aluno' AND a.ativo = 1 AND "
        "(a.instrutor_id = p.id OR EXISTS (SELECT 1 FROM vinculos v WHERE v.aluno_id = a.id AND v.professor_id = p.id))) "
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
            novo_id = db.insert("INSERT INTO usuarios (nome, email, senha_hash, perfil, telefone, admin, trocar_senha) "
                                "VALUES (?, ?, ?, 'instrutor', ?, ?, 1)",
                                (dados["nome"], dados["email"], generate_password_hash(senha), dados["telefone"], dados["admin"]))
            msg = _aplicar_alunos(novo_id, request.form)
            if msg:
                flash(msg, "ok")
            return render_template("aluno_acesso.html", nome=dados["nome"], email=dados["email"], senha=senha,
                                   titulo="Professor cadastrado", voltar=url_for("professor_editar", prof_id=novo_id),
                                   voltar_txt="Ver o professor")
    return render_template("professor_form.html", prof=dados, novo=True, senha_min=SENHA_MIN,
                           todos_alunos=_todos_alunos(), marcados={int(x) for x in request.form.getlist("aluno_ids") if x.isdigit()})


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
    alunos = db.query_all(f"SELECT u.id, u.nome, u.ativo, u.instrutor_id FROM usuarios u WHERE u.perfil = 'aluno' "
                          f"AND {sql_acesso()} ORDER BY u.nome", params_acesso(prof_id))
    for a in alunos:
        a["principal"] = a["instrutor_id"] == prof_id
        a["outros"] = [p for p in vinculos.professores_do_aluno(a["id"]) if p["id"] != prof_id]
    ids = {a["id"] for a in alunos}
    return render_template("professor_form.html", prof=prof, novo=False, senha_min=SENHA_MIN, alunos=alunos,
                           eu=prof_id == user["id"], todos_alunos=[a for a in _todos_alunos() if a["id"] not in ids],
                           marcados=set())


@app.route("/instrutor/professores/<int:prof_id>/alunos", methods=["POST"])
@admin_obrigatorio
def professor_alunos(user, prof_id):
    """Vincula (acrescenta) ou transfere (passa a ser o único professor) os alunos marcados."""
    _professor(prof_id)
    msg = _aplicar_alunos(prof_id, request.form)
    flash(msg or "Marque pelo menos um aluno.", "ok" if msg else "erro")
    return redirect(url_for("professor_editar", prof_id=prof_id) + "#alunos")


@app.route("/instrutor/professores/<int:prof_id>/alunos/<int:aluno_id>/remover", methods=["POST"])
@admin_obrigatorio
def professor_desvincular(user, prof_id, aluno_id):
    _professor(prof_id)
    erro = vinculos.desvincular(aluno_id, prof_id)
    flash(erro or "Aluno desvinculado deste professor.", "erro" if erro else "ok")
    destino = request.form.get("voltar")
    if destino == "aluno":
        return redirect(url_for("aluno_editar", aluno_id=aluno_id) + "#professores")
    return redirect(url_for("professor_editar", prof_id=prof_id) + "#alunos")


@app.route("/instrutor/alunos/<int:aluno_id>/professores", methods=["POST"])
@admin_obrigatorio
def aluno_vincular_professor(user, aluno_id):
    """Na ficha do aluno: acrescentar um professor."""
    if not db.query_one("SELECT id FROM usuarios WHERE id = ? AND perfil = 'aluno'", (aluno_id,)):
        abort(404)
    try:
        prof_id = int(request.form.get("professor_id", ""))
    except ValueError:
        prof_id = 0
    if not db.query_one("SELECT id FROM usuarios WHERE id = ? AND perfil = 'instrutor' AND ativo = 1", (prof_id,)):
        flash("Escolha um professor ativo.", "erro")
    elif request.form.get("modo") == "transferir":
        vinculos.transferir(aluno_id, prof_id)
        flash("Aluno transferido: agora tem só esse professor.", "ok")
    else:
        flash("Professor vinculado ao aluno." if vinculos.vincular(aluno_id, prof_id) else "Esse professor já acompanha o aluno.", "ok")
    if prof_id and prof_id != user["id"] and request.form.get("modo") == "transferir":
        return redirect(url_for("alunos"))   # o administrador pode ter perdido o acesso a esse aluno
    return redirect(url_for("aluno_editar", aluno_id=aluno_id) + "#professores")


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
    """Passa os alunos deste professor para outro (ex.: antes de desativá-lo); os demais professores de cada aluno ficam."""
    _professor(prof_id)
    try:
        destino = int(request.form.get("destino", ""))
    except ValueError:
        destino = 0
    alvo = db.query_one("SELECT id, nome FROM usuarios WHERE id = ? AND perfil = 'instrutor' AND ativo = 1", (destino,))
    if not alvo or destino == prof_id:
        flash("Escolha um professor ativo para receber os alunos.", "erro")
    else:
        n = vinculos.substituir(prof_id, destino)
        flash(f"{n} aluno{'s' if n != 1 else ''} transferido{'s' if n != 1 else ''} para {alvo['nome']}.", "ok")
    return redirect(url_for("professor_editar", prof_id=prof_id))


@app.context_processor
def _outros_professores():
    def outros(exceto):
        return db.query_all("SELECT id, nome FROM usuarios WHERE perfil = 'instrutor' AND ativo = 1 AND id <> ? ORDER BY nome",
                            (exceto,))
    return {"outros_professores": outros}
