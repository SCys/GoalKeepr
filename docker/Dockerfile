FROM python:3.14-alpine

# Install system dependencies
RUN apk add --no-cache ffmpeg

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
RUN uv --version

WORKDIR /app

# Copy dependency files for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies into .venv (no dev dependencies)
RUN uv sync --frozen --no-dev

# Copy the rest of the application
COPY . .

# Re-sync to ensure .venv is intact after COPY (no-op if unchanged, fast)
RUN uv sync --frozen --no-dev

# Ensure startup script is executable
RUN chmod +x docker/startup.sh

# Create runtime directories
RUN mkdir -p data log

# Add virtual environment to PATH
ENV PATH="/app/.venv/bin:$PATH"

CMD ["sh", "docker/startup.sh"]