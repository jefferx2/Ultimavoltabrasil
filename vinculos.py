"""Vínculo aluno ↔ professores.

Cada aluno tem um professor principal (usuarios.instrutor_id) e pode ter professores adicionais (tabela vinculos).
Todos os vinculados veem, montam treinos e acompanham o aluno.
"""
import db


def sql_acesso(alias="u"):
    """Condição SQL: o usuário `alias` é aluno do professor informado (usar com params_acesso)."""
    return (f"({alias}.instrutor_id = ? OR EXISTS (SELECT 1 FROM vinculos v "
            f"WHERE v.aluno_id = {alias}.id AND v.professor_id = ?))")


def params_acesso(professor_id):
    return (professor_id, professor_id)


def professores_do_aluno(aluno_id):
    aluno = db.query_one("SELECT instrutor_id FROM usuarios WHERE id = ?", (aluno_id,))
    lista = db.query_all(
        "SELECT p.id, p.nome, p.ativo FROM usuarios p WHERE p.id = ? "
        "UNION SELECT p.id, p.nome, p.ativo FROM usuarios p JOIN vinculos v ON v.professor_id = p.id WHERE v.aluno_id = ?",
        (aluno["instrutor_id"] if aluno else None, aluno_id))
    for p in lista:
        p["principal"] = aluno is not None and p["id"] == aluno["instrutor_id"]
    return sorted(lista, key=lambda p: (not p["principal"], p["nome"]))


def vincular(aluno_id, professor_id):
    """Acrescenta o professor (o aluno continua com os atuais). Devolve True se mudou algo."""
    aluno = db.query_one("SELECT instrutor_id FROM usuarios WHERE id = ?", (aluno_id,))
    if aluno["instrutor_id"] is None:
        db.execute("UPDATE usuarios SET instrutor_id = ? WHERE id = ?", (professor_id, aluno_id))
        return True
    if aluno["instrutor_id"] == professor_id or db.query_one(
            "SELECT 1 AS x FROM vinculos WHERE aluno_id = ? AND professor_id = ?", (aluno_id, professor_id)):
        return False
    db.execute("INSERT INTO vinculos (aluno_id, professor_id) VALUES (?, ?)", (aluno_id, professor_id))
    return True


def transferir(aluno_id, professor_id):
    """O professor passa a ser o único do aluno."""
    with db.Transacao() as t:
        t.execute("UPDATE usuarios SET instrutor_id = ? WHERE id = ?", (professor_id, aluno_id))
        t.execute("DELETE FROM vinculos WHERE aluno_id = ?", (aluno_id,))


def desvincular(aluno_id, professor_id):
    """Remove o professor do aluno. Se era o principal, outro vinculado assume. Não deixa o aluno sem professor:
    devolve uma mensagem de erro nesse caso (senão None)."""
    aluno = db.query_one("SELECT instrutor_id FROM usuarios WHERE id = ?", (aluno_id,))
    extras = [r["professor_id"] for r in db.query_all(
        "SELECT professor_id FROM vinculos WHERE aluno_id = ? ORDER BY professor_id", (aluno_id,))]
    if aluno["instrutor_id"] == professor_id:
        if not extras:
            return "O aluno precisa ter pelo menos um professor. Vincule outro antes de remover este."
        with db.Transacao() as t:
            t.execute("UPDATE usuarios SET instrutor_id = ? WHERE id = ?", (extras[0], aluno_id))
            t.execute("DELETE FROM vinculos WHERE aluno_id = ? AND professor_id = ?", (aluno_id, extras[0]))
        return None
    db.execute("DELETE FROM vinculos WHERE aluno_id = ? AND professor_id = ?", (aluno_id, professor_id))
    return None


def substituir(professor_de, professor_para):
    """Em todos os alunos de `professor_de`, troca por `professor_para` (mantém os demais professores)."""
    alunos = db.query_all(f"SELECT u.id, u.instrutor_id FROM usuarios u WHERE u.perfil = 'aluno' AND {sql_acesso()}",
                          params_acesso(professor_de))
    with db.Transacao() as t:
        for a in alunos:
            if a["instrutor_id"] == professor_de:
                t.execute("UPDATE usuarios SET instrutor_id = ? WHERE id = ?", (professor_para, a["id"]))
                t.execute("DELETE FROM vinculos WHERE aluno_id = ? AND professor_id = ?", (a["id"], professor_para))
            else:
                ja = t.query_all("SELECT 1 AS x FROM vinculos WHERE aluno_id = ? AND professor_id = ?", (a["id"], professor_para))
                if ja or a["instrutor_id"] == professor_para:
                    t.execute("DELETE FROM vinculos WHERE aluno_id = ? AND professor_id = ?", (a["id"], professor_de))
                else:
                    t.execute("UPDATE vinculos SET professor_id = ? WHERE aluno_id = ? AND professor_id = ?",
                              (professor_para, a["id"], professor_de))
    return len(alunos)
