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

## Professores e acompanhamento
- O primeiro professor cadastrado é o **administrador** (menu "Professores"): cadastra outros professores,
  redefine senhas, desativa e transfere alunos. Cada professor vê só os próprios alunos.
  Pela linha de comando: `flask --app app criar-usuario --admin`.
- O aluno registra cada treino em "Treinos da semana" → "Registrar treino" (`rotas_acompanhamento.py`,
  `registros.py`). O professor acompanha em "Acompanhamento".

## Velocidade
- Fontes servidas pelo próprio site (`static/fonts`, licença OFL) — sem chamadas ao Google.
- Arquivos estáticos com cache de 1 ano; a URL leva a versão (`?v=`), então mudanças chegam na hora.
- Cada resposta traz o cabeçalho `Server-Timing` (F12 > Rede > Tempo): tempo total, tempo no banco e nº de consultas.
- Páginas acima de `LIMITE_LENTO_MS` (padrão 500 ms) vão para o log: `journalctl -u ultimavolta | grep LENTO`.
- Gunicorn com threads: `--worker-class gthread --threads 4 -w 2`.
