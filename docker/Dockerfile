FROM python:3.14-slim AS builder

WORKDIR /app
COPY pyproject.toml README.md ./
COPY posipaka/ ./posipaka/

RUN pip install --no-cache-dir ".[telegram]"

# ─── Production ──────────────────────────────────────────────────────────────
FROM python:3.14-slim

RUN groupadd -r agent && useradd -r -g agent -d /home/agent agent \
    && mkdir -p /home/agent/.posipaka \
    && chown -R agent:agent /home/agent

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/posipaka /usr/local/bin/posipaka
COPY --from=builder /app/posipaka /app/posipaka

WORKDIR /app
USER agent

VOLUME ["/home/agent/.posipaka"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/api/v1/health').raise_for_status()" || exit 1

ENTRYPOINT ["python", "-m", "posipaka"]
CMD ["start"]
