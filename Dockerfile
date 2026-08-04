FROM python:3.12-slim

# Allows hatch-vcs to determine version without .git history
ARG PACKAGE_VERSION=dev
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${PACKAGE_VERSION}

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install uv package manager for faster installs
RUN pip install --no-cache-dir uv

# Create working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml requirements.txt ./

# Install dependencies using uv
RUN uv pip install --system -r requirements.txt

# Copy source code
COPY src/ ./src/

# Copy configuration files
COPY configs/ ./configs/

# Create non-root user for security
RUN useradd -m -u 1000 mcpuser && \
    chown -R mcpuser:mcpuser /app

USER mcpuser

# HTTP transport default port (see --transport http / --stateless)
EXPOSE 8000

# Container stays alive waiting for exec commands
# This allows "podman exec -i bitbucket-mcp uv run src/main.py"
CMD ["tail", "-f", "/dev/null"]
