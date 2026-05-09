FROM python:3.11-slim

LABEL maintainer="kenan"
LABEL description="OpenAI-compatible API server powered by GitHub Copilot SDK"

# Prevent Python from buffering stdout/stderr (important for Docker logs)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default config path inside the container
ENV CONFIG_PATH=/config/config.yaml

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY copilot_gateway/ ./copilot_gateway/

# Add custom tools directory to Python path so mounted tools are importable
ENV PYTHONPATH="/custom-tools:${PYTHONPATH}"

# Create directories for config and custom tools
RUN mkdir -p /config /custom-tools

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app /config /custom-tools
USER appuser

EXPOSE 3001

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:3001/health')" || exit 1

ENTRYPOINT ["python", "-m", "uvicorn", "copilot_gateway.main:app", \
    "--host", "0.0.0.0", "--port", "3001"]
