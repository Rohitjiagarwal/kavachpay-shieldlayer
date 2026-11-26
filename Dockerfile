# KavachPay in one container: FastAPI serves the API *and* the static dashboard
# on port 7860 (the Hugging Face Spaces default).
#
#   docker build -t kavachpay .
#   docker run -p 7860:7860 -e GEMINI_API_KEY=... -e SESSION_SECRET=... kavachpay
#
# deploy/huggingface/Dockerfile is the same recipe, cloning from GitHub instead.

# ---------- 1. dashboard -> static files ----------
FROM node:22-slim AS web
WORKDIR /web
RUN corepack enable
COPY dashboard/package.json dashboard/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY dashboard/ ./
ENV STATIC_EXPORT=1 NEXT_PUBLIC_SAME_ORIGIN=1 NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

# ---------- 2. API + funnel ----------
FROM python:3.12-slim
RUN useradd -m -u 1000 user
ENV HOME=/home/user PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/home/user/.cache/fastembed
WORKDIR /home/user/app
RUN pip install uv
COPY --chown=user pyproject.toml README.md ./
COPY --chown=user shared ./shared
COPY --chown=user shield ./shield
COPY --chown=user app ./app
COPY --chown=user config ./config
COPY --chown=user rules ./rules
COPY --chown=user attacks ./attacks
RUN uv pip install --system -e ".[app]" && chown -R user /home/user/app
COPY --from=web --chown=user /web/out ./dashboard/out

USER user
RUN python -c "from app.rag import embed; embed.embed_one('warm up the embedding cache')"

ENV PUBLIC_DEMO=1 \
    CHAT_PROVIDER=gemini \
    LAYER2_PROVIDER=auto \
    LAYER2_ALLOW_HEURISTIC_FALLBACK=true \
    SHIELD_URL= \
    DASHBOARD_DIR=/home/user/app/dashboard/out \
    TRUST_PROXY=1 \
    UPLOAD_MAX_MB=2 \
    ENRICH_CONTEXT=false
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
