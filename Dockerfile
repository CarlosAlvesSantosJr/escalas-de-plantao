FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ESCALA_DADOS=/data/dados_escala.json \
    TZ=America/Sao_Paulo

WORKDIR /app

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY escala/ escala/
COPY static/ static/
COPY webapp.py .

# Usuário sem privilégios; /data guarda o JSON da escala (montado como volume).
RUN useradd --create-home --uid 1000 escala \
    && mkdir -p /data && chown escala:escala /data
USER escala
VOLUME ["/data"]

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/saude')" || exit 1

# Um único worker: o repositório JSON usa lock em memória, que não é
# compartilhado entre processos. Threads dão conta do uso doméstico.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "--no-control-socket", "webapp:create_app()"]
