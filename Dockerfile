FROM python:3.13-slim-bookworm

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

# Install with slack + telemetry extras so the default container can run the
# Slack bot out of the box and export OTel traces. Users who don't need them
# just ignore the extra deps.
RUN pip install --no-cache-dir ".[slack,telemetry]"

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["ds", "serve", "--host", "0.0.0.0", "--port", "8000"]
