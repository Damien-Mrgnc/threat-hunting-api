FROM python:3.12-slim

WORKDIR /app

RUN pip install fastapi uvicorn jinja2 markdown httpx

# App portal
COPY portal/app /app

# Threat Interface SPA (HTML/JS/CSS)
COPY interface/ /app/interface/

# Documentation interne (fichiers .md du projet)
RUN mkdir -p /docs_mount
COPY docs/ /docs_mount/

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8088"]
