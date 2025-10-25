FROM python:3.11-slim

# Minimal image for running the SQL MCP server
ENV PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.0

WORKDIR /app

# Install system deps required by some DB drivers (kept minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . /app

# Install package and runtime deps
RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir -e .[parsing] || python -m pip install --no-cache-dir -e .

EXPOSE 8080

# Run the MCP server (fastmcp must be installed in the image or available via extras)
CMD ["python", "-m", "sql_mcp_server.server"]
