FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
COPY shared ./shared
COPY shield ./shield
COPY config ./config
COPY rules ./rules
RUN uv pip install --system -e "."
EXPOSE 8090
CMD ["python", "-m", "uvicorn", "shield.app:app", "--host", "0.0.0.0", "--port", "8090"]
