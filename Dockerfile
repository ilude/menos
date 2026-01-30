FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install dependencies
RUN uv pip install --system -e .

# Create data directory
RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "menos.main:app", "--host", "0.0.0.0", "--port", "8000"]
