"""Conteúdo da página inicial. Edite aqui para publicar novos artigos.

Cada artigo: data (AAAA-MM-DD), título, resumo curto, assunto (Pista, Rua ou Saúde) e o link do post.
Para o link: abra o post no Substack e copie o endereço (ex.: https://ultimavoltabrasil.substack.com/p/...).
"""
SUBSTACK = "https://ultimavoltabrasil.substack.com"
ARQUIVO = SUBSTACK + "/archive"

ARTIGOS = [
    {"data": "2026-03-12", "assunto": "Rua", "link": ARQUIVO,
     "titulo": "O ritmo necessário para subir no pódio nos 5 km",
     "resumo": "Qual pace separa quem chega no pódio de quem chega logo atrás numa prova de 5 km."},
    {"data": "2026-03-11", "assunto": "Saúde", "link": ARQUIVO,
     "titulo": "Corrida pode ajudar a controlar a hipertensão? A ciência diz que sim.",
     "resumo": "O que os estudos mostram sobre condicionamento aeróbico e pressão arterial."},
    {"data": "2026-03-05", "assunto": "Rua", "link": ARQUIVO,
     "titulo": "Correr é diferente de treinar corrida.",
     "resumo": "Por que correr com frequência não é o mesmo que seguir um treino com objetivo."},
    {"data": "2026-03-03", "assunto": "Pista", "link": ARQUIVO,
     "titulo": "A importância da consistência na última volta.",
     "resumo": "Nos 800 metros, a prova raramente se resolve na largada. Como o ritmo constante decide o fim."},
]
