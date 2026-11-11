"""Mede a distância (latência) entre este servidor e o banco.

No VPS:
  sudo -u ultimavolta bash -c 'set -a; . /etc/ultimavolta.env; set +a; cd /opt/ultimavolta/app && ../venv/bin/python diagnostico_banco.py'
"""
import os
import time

import psycopg

url = os.environ.get("DATABASE_URL", "")
if not url.startswith("postgres"):
    raise SystemExit("DATABASE_URL não definida (rode com o /etc/ultimavolta.env carregado).")

conexoes = []
for _ in range(3):
    t0 = time.perf_counter()
    conn = psycopg.connect(url)
    conexoes.append((time.perf_counter() - t0) * 1000)
consultas = []
for _ in range(10):
    t0 = time.perf_counter()
    conn.execute("SELECT 1").fetchone()
    consultas.append((time.perf_counter() - t0) * 1000)
host = conn.info.host
conn.close()

print(f"Banco: {host}")
print(f"Abrir uma conexão nova: {min(conexoes):.0f} ms (melhor de 3)")
print(f"Uma consulta numa conexão aberta: {min(consultas):.0f} ms (ida e volta)")
rtt = min(consultas)
if rtt < 15:
    print("Ótimo: o servidor está perto do banco.")
elif rtt < 60:
    print("Razoável: o pool de conexões resolve bem.")
else:
    print("Alto: o VPS e o banco estão longe. Considere deixar os dois na mesma região (ex.: São Paulo).")
