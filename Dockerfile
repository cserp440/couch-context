FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Copy source code
COPY src/ /app/src/

# Set Python path
ENV PYTHONPATH=/app/src

# Run the MCP server
ENTRYPOINT ["python", "-m", "cb_memory.server"]
