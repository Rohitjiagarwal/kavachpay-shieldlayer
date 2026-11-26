# API-only container for Render Free Tier (512 MB RAM) paired with Vercel frontend.
FROM python:3.12-slim
RUN useradd -m -u 1000 user
ENV HOME=/home/user PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /home/user/app

RUN pip install --no-cache-dir uv
COPY --chown=user pyproject.toml README.md ./
COPY --chown=user shared ./shared
COPY --chown=user shield ./shield
COPY --chown=user app ./app
COPY --chown=user config ./config
COPY --chown=user rules ./rules
COPY --chown=user attacks ./attacks
RUN uv pip install --system -e ".[api-lite]" && chown -R user /home/user/app

USER user

ENV PUBLIC_DEMO=1 \
    CROSS_SITE_COOKIES=1 \
    DISABLE_FASTEMBED=1 \
    CHAT_PROVIDER=gemini \
    LAYER2_PROVIDER=auto \
    LAYER2_ALLOW_HEURISTIC_FALLBACK=true \
    SHIELD_URL= \
    TRUST_PROXY=1 \
    UPLOAD_MAX_MB=2 \
    ENRICH_CONTEXT=false \
    PORT=8080

EXPOSE 8080
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips '*'"]
