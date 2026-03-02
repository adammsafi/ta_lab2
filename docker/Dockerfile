FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (gcc for C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install ta_lab2 with orchestrator extras + MCP deps
# NOTE: fastmcp pulls in the mcp SDK as dependency, do NOT install mcp separately
RUN pip install --no-cache-dir ".[orchestrator]" "fastmcp>=3.0.0" "uvicorn[standard]"

EXPOSE 8080

# Health check -- hit the REST health endpoint
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["uvicorn", "ta_lab2.tools.ai_orchestrator.memory.server:app", \
     "--host", "0.0.0.0", "--port", "8080"]
