# Hugging Face Space for KavachPay. This Space holds only this file and README.md:
# the image is built from the public GitHub repo, so the GitHub repo stays the
# single source of truth. Same recipe as the repo's root Dockerfile.
#
# Space variables (Settings -> Variables and secrets):
#   secret   GEMINI_API_KEY   optional key for Gemini chat + Layer 2 extractor
#   secret   SESSION_SECRET   any long random string (signs the cookies)
#   secret   ADMIN_TOKEN      any long random string
#   variable GITHUB_REPO      <you>/kavachpay  (must be public)
# Optional: DEMO_REQUEST_LIMIT (4), DEMO_DAILY_LIMIT (250), GEMINI_CHAT_MODEL.

# ---------- 0. source ----------
FROM alpine/git:2.47.2 AS src
ARG GITHUB_REPO
ARG REPO_REF=main
ADD "https://api.github.com/repos/${GITHUB_REPO}/commits/${REPO_REF}" /tmp/latest-commit.json
RUN git clone --depth 1 --branch "$REPO_REF" "https://github.com/${GITHUB_REPO}.git" /src

# ---------- 1. dashboard -> static files ----------
FROM node:22-slim AS web
WORKDIR /web
RUN corepack enable
COPY --from=src /src/dashboard/package.json /src/dashboard/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY --from=src /src/dashboard/ ./
ENV STATIC_EXPORT=1 NEXT_PUBLIC_SAME_ORIGIN=1 NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

# ---------- 2. API + funnel ----------
FROM python:3.12-slim
RUN useradd -m -u 1000 user
ENV HOME=/home/user PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/home/user/.cache/fastembed
WORKDIR /home/user/app
RUN pip install uv
COPY --from=src --chown=user /src/pyproject.toml /src/README.md ./
COPY --from=src --chown=user /src/shared ./shared
COPY --from=src --chown=user /src/shield ./shield
COPY --from=src --chown=user /src/app ./app
COPY --from=src --chown=user /src/config ./config
COPY --from=src --chown=user /src/rules ./rules
COPY --from=src --chown=user /src/attacks ./attacks
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
