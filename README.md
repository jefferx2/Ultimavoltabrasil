# Última Volta Brasil — sistema de treinos

Flask + SQLite local / Postgres (Supabase) em produção. Login único que leva para a área do **instrutor** ou do **aluno**.

## Rodar local (VS Code)
```bash
python -m venv venv
venv\Scripts\activate            # Windows
python -m pip install -r requirements.txt
flask --app app criar-usuario    # cria o primeiro instrutor
flask --app app run --debug
```
Abra http://127.0.0.1:5000

## Variáveis (`/etc/ultimavolta.env` no VPS)
```
FLASK_ENV=production
SECRET_KEY=<gerar com: python3 -c "import secrets; print(secrets.token_hex(32))">
DATABASE_URL=postgresql://usuario:senha@host:5432/postgres
```
`SECRET_KEY` é obrigatória em produção (sem ela, cada worker do gunicorn gera uma chave diferente e o login cai).

## Estrutura
- `app.py` — rotas: `/` (página inicial), `/login`, `/sair`, `/instrutor`, `/aluno`; comando `criar-usuario`
- `db.py` — camada SQLite/Postgres e criação da tabela `usuarios`
- `templates/`, `static/css/style.css`
- Logo: coloque o arquivo em `static/img/logo.png` que ele aparece automaticamente no topo.

## Serviço (gunicorn)
```
ExecStart=/opt/ultimavolta/venv/bin/gunicorn -w 2 -b 127.0.0.1:<PORTA> app:app
```

## Desempenho
- No Postgres as conexões ficam num **pool** por processo e cada página usa **uma só conexão**
  (`db.py`). Tamanho máximo do pool por processo: variável `DB_POOL_MAX` (padrão 4).
  Com 2 processos do gunicorn são no máximo 8 conexões, abaixo do limite do Session pooler do Supabase.
- Diagnóstico da distância até o banco: `diagnostico_banco.py` (instruções no próprio arquivo).
