FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/manzzaano/leo-code"
LABEL org.opencontainers.image.description="KC-RAG Sidecar — Structural code retrieval"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Instalar dependencias del sistema necesarias para sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Instalar leo-code desde el repo local (modo editable)
COPY . /app
RUN pip install --no-cache-dir -e ".[all]"

# Cache dir para Qdrant local e índices
RUN mkdir -p /cache
VOLUME /cache

EXPOSE 9898

ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:9898/health').raise_for_status()" || exit 1

ENTRYPOINT ["leo-code-mcp"]
CMD ["--host", "0.0.0.0", "--port", "9898", "--workers", "2"]
