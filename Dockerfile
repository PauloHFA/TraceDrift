# Multi-stage Docker build for TraceDrift
FROM python:3.12-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md LICENSE ./
COPY tracedrift/ ./tracedrift/

RUN uv build --wheel

FROM python:3.12-slim AS runner

WORKDIR /app

COPY --from=builder /app/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -rf /tmp/*.whl

COPY configs/ ./configs/

ENTRYPOINT ["tracedrift"]
CMD ["--help"]
