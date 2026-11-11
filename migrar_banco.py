"""Copia todos os dados do banco atual para um banco novo (ex.: projeto Supabase em São Paulo).

Uso no VPS (com o sistema PARADO, para ninguém gravar durante a cópia):
  systemctl stop ultimavolta
  sudo -u ultimavolta bash -c 'set -a; . /etc/ultimavolta.env; set +a; cd /opt/ultimavolta/app && ../venv/bin/python migrar_banco.py'

- Origem: o DATABASE_URL atual (lido do /etc/ultimavolta.env).
- Destino: o endereço do banco novo, pedido na tela (não fica no histórico do terminal).
- O destino precisa estar vazio. As tabelas são criadas pelo próprio sistema; os ids são mantidos.
- Nada é apagado da origem: se algo der errado, basta continuar usando o banco antigo.
"""
import getpass
import os
import sys

import psycopg
from psycopg.rows import dict_row

# Ordem de cópia (respeita as chaves estrangeiras)
ORDEM = ["usuarios", "vinculos", "avaliacoes", "macrociclos", "fases", "treinos", "treino_academia",
         "treino_corrida", "registros", "registro_corrida", "registro_series"]


def colunas(conn, tabela):
    return [r["column_name"] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = %s ORDER BY ordinal_position", (tabela,)).fetchall()]


def existe(conn, tabela):
    return conn.execute("SELECT to_regclass(%s) AS t", (tabela,)).fetchone()["t"] is not None


def main():
    origem = os.environ.get("ORIGEM_URL") or os.environ.get("DATABASE_URL", "")
    if not origem.startswith("postgres"):
        sys.exit("Origem não encontrada: rode com o /etc/ultimavolta.env carregado (DATABASE_URL).")
    destino = os.environ.get("DESTINO_URL") or getpass.getpass("Endereço do banco NOVO (Session pooler, com a senha): ").strip()
    if not destino.startswith("postgres"):
        sys.exit("Endereço do destino inválido: precisa começar com postgresql://")
    if destino == origem:
        sys.exit("Origem e destino são o mesmo banco.")

    # 1) cria as tabelas no destino usando o próprio sistema (mesmo esquema, RLS e colunas)
    os.environ["DATABASE_URL"] = destino
    import db
    db.init_db()
    print("Tabelas criadas no destino.")

    with psycopg.connect(origem, row_factory=dict_row) as o, psycopg.connect(destino, row_factory=dict_row) as d:
        if d.execute("SELECT COUNT(*) AS n FROM usuarios").fetchone()["n"]:
            sys.exit("O banco de destino já tem usuários. Use um projeto novo e vazio.")
        total = {}
        for tabela in ORDEM:
            if not existe(o, tabela):
                total[tabela] = 0
                continue
            cols = [c for c in colunas(o, tabela) if c in set(colunas(d, tabela))]
            linhas = o.execute(f"SELECT {', '.join(cols)} FROM {tabela} ORDER BY 1").fetchall()
            if tabela == "usuarios":  # instrutor_id aponta para a própria tabela: grava depois
                instrutores = [(l["instrutor_id"], l["id"]) for l in linhas if l.get("instrutor_id")]
                for l in linhas:
                    l["instrutor_id"] = None
            if linhas:
                marcas = ", ".join(["%s"] * len(cols))
                with d.cursor() as cur:
                    cur.executemany(f"INSERT INTO {tabela} ({', '.join(cols)}) VALUES ({marcas})",
                                    [tuple(l[c] for c in cols) for l in linhas])
            if tabela == "usuarios" and instrutores:
                with d.cursor() as cur:
                    cur.executemany("UPDATE usuarios SET instrutor_id = %s WHERE id = %s", instrutores)
            # sequência do id continua de onde parou (novos cadastros não colidem)
            if "id" in cols:
                d.execute(f"SELECT setval(pg_get_serial_sequence('{tabela}', 'id'), "
                          f"COALESCE((SELECT MAX(id) FROM {tabela}), 1), (SELECT COUNT(*) FROM {tabela}) > 0)")
            total[tabela] = len(linhas)
        d.commit()

        # 2) confere: mesma quantidade de linhas nos dois bancos
        ok = True
        print("\nTabela              origem  destino")
        for tabela in ORDEM:
            n_o = o.execute(f"SELECT COUNT(*) AS n FROM {tabela}").fetchone()["n"] if existe(o, tabela) else 0
            n_d = d.execute(f"SELECT COUNT(*) AS n FROM {tabela}").fetchone()["n"]
            marca = "ok" if n_o == n_d else "DIFERENTE"
            ok = ok and n_o == n_d
            print(f"{tabela:<18} {n_o:>7} {n_d:>8}  {marca}")
    if ok:
        print("\nCópia concluída e conferida. Agora troque o DATABASE_URL no /etc/ultimavolta.env pelo endereço novo.")
    else:
        sys.exit("\nAs contagens não bateram. NÃO troque o DATABASE_URL; me mande esta saída.")


if __name__ == "__main__":
    main()
