FROM python:3.12-alpine

# Install system dependencies
RUN apk add --no-cache ffmpeg nodejs

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
RUN uv --version

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy the rest of the application
COPY . .

# Add virtual environment to PATH
ENV PATH="/app/.venv/bin:$PATH"

CMD ["sh", "startup.sh"]