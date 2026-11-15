"""Ponto de entrada na Vercel (veja pyproject.toml → [tool.vercel] entrypoint).

Na Vercel não há disco: com DATABASE_URL definida (integração Neon), a escala,
os usuários e a auditoria ficam no Postgres. Guia: docs/VERCEL.md.
"""
from webapp import create_app, url_do_banco

if not url_do_banco():
    raise RuntimeError("Defina DATABASE_URL (Postgres/Neon). Na Vercel: Storage → Neon → Connect.")

app = create_app()
