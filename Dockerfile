FROM python:3.11-slim AS builder
WORKDIR /build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
COPY pyproject.toml ./
COPY src/ src/
ARG PIP_EXTRA_INDEX_URL=""
RUN grep -v 'tool.uv.sources\|editable = true\|path = "\.\.' pyproject.toml > pyproject.clean.toml && \
    mv pyproject.clean.toml pyproject.toml && \
    uv pip install --system --index-url "https://pypi.org/simple/" \
      --extra-index-url "${PIP_EXTRA_INDEX_URL}" .

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1
CMD ["uvicorn", "ember_api.main:app", "--host", "0.0.0.0", "--port", "8080"]
