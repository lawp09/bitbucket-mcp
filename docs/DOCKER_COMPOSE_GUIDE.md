# Docker Compose Guide for Bitbucket MCP Server

A complete guide to running the Bitbucket MCP server using Docker Compose. This guide covers setup, configuration, troubleshooting, and integration with AI tools.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Prerequisites](#prerequisites)
3. [Detailed Setup Instructions](#detailed-setup-instructions)
4. [Usage](#usage)
5. [Configuration Options](#configuration-options)
6. [Health Checks and Monitoring](#health-checks-and-monitoring)
7. [Troubleshooting by Platform](#troubleshooting-by-platform)
8. [Integration with Claude Desktop/GitHub Copilot](#integration-with-claude-desktopgithub-copilot)
9. [Common Issues and Solutions](#common-issues-and-solutions)
10. [Advanced Usage](#advanced-usage)

---

## Quick Start

Get the Bitbucket MCP server running in 3 simple steps.

### Step 1: Copy and Fill Environment Variables

```bash
# Copy the example file
cp env.example .env

# Edit with your credentials (use your preferred editor)
# macOS/Linux
nano .env

# Windows (PowerShell)
notepad .env
```

Required variables to fill:
```env
BITBUCKET_USERNAME=your-email@example.com
BITBUCKET_TOKEN=your-192-character-app-password
BITBUCKET_WORKSPACE=your-workspace-name
```

### Step 2: Build the Container

```bash
# Using Docker Compose
docker-compose build

# Or using the provided script
./scripts/build.sh

# If you use Podman instead
podman-compose build
```

### Step 3: Start the Server

```bash
# Using Docker Compose
docker-compose up -d

# Or using the provided script
./scripts/run.sh

# Using Podman
podman-compose up -d
```

**That's it!** Your Bitbucket MCP server is now running.

To verify it's working:
```bash
docker-compose ps
# or
podman-compose ps
```

You should see the `bitbucket-mcp` container with status `Up`.

---

## Prerequisites

### Required Software

Choose one container runtime (you likely have one already):

**Docker & Docker Compose** (Recommended)
```bash
# macOS (via Homebrew)
brew install docker

# Windows
# Download Docker Desktop from https://www.docker.com/products/docker-desktop

# Linux
sudo apt-get install docker.io docker-compose  # Ubuntu/Debian
sudo dnf install docker docker-compose          # Fedora
```

**OR Podman & Podman Compose**
```bash
# macOS (via Homebrew)
brew install podman podman-compose

# Linux
sudo apt-get install podman podman-compose  # Ubuntu/Debian
sudo dnf install podman podman-compose      # Fedora

# Windows (via WSL2)
# Install WSL2, then install podman inside WSL2
```

**Check your installation:**
```bash
docker --version
docker-compose --version

# OR
podman --version
podman-compose --version
```

### Bitbucket Credentials

You need a Bitbucket app password. This is **not** your account password.

**To generate an app password:**

1. Go to [Bitbucket Settings → App passwords](https://bitbucket.org/account/settings/app-passwords/)
2. Click "Create app password"
3. Give it a name: `Bitbucket MCP Server`
4. Select these permissions:
   - Repositories: Read and Write
   - Pull requests: Read and Write
   - Pipelines: Read
5. Click "Create"
6. Copy the generated 192-character password (you won't see it again)

**Your credentials include:**
- **Email**: Your Bitbucket account email
- **Token**: The 192-character app password you just created
- **Workspace**: Your Bitbucket workspace name (visible in your workspace URL)

---

## Detailed Setup Instructions

### Step 1: Prepare Your Environment

Create a `.env` file from the example:

```bash
cp env.example .env
```

### Step 2: Fill in Your Credentials

Edit the `.env` file with your favorite text editor:

```env
# Your Bitbucket account email
BITBUCKET_USERNAME=your-email@example.com

# Your 192-character app password (created in prerequisites)
BITBUCKET_TOKEN=ABCDEFGHIJKLMNOPQRSTUVWXYZ...

# Your Bitbucket workspace name
# Example: if your URL is https://bitbucket.org/myworkspace/repo
# Then your workspace is "myworkspace"
BITBUCKET_WORKSPACE=your-workspace-name

# Optional: Bitbucket API base URL (usually leave as default)
# BITBUCKET_BASE_URL=https://api.bitbucket.org

# Optional: Log level (DEBUG, INFO, WARNING, ERROR)
# LOG_LEVEL=INFO
```

### Step 3: Build the Container Image

The first time, you need to build the Docker image. This downloads dependencies and prepares the container.

**Using Docker Compose:**
```bash
docker-compose build
```

**Using Podman Compose:**
```bash
podman-compose build
```

**Using the provided script:**
```bash
./scripts/build.sh
```

You'll see output like:
```
Building Bitbucket MCP container...
[+] Building 45.3s (11/11) FINISHED
```

This takes 1-2 minutes the first time. Subsequent builds are faster.

### Step 4: Start the Container

**Using Docker Compose:**
```bash
docker-compose up -d
```

**Using Podman Compose:**
```bash
podman-compose up -d
```

**Using the provided script:**
```bash
./scripts/run.sh
```

The `-d` flag runs it in the background (detached mode).

### Step 5: Verify the Container is Running

```bash
# Check container status
docker-compose ps

# View recent logs
docker-compose logs bitbucket-mcp
```

Expected output:
```
NAME              STATUS
bitbucket-mcp     Up 2 seconds (healthy)
```

If you see a different status, see the [Troubleshooting](#troubleshooting-by-platform) section.

---

## Usage

Common commands for managing your Bitbucket MCP server.

### Starting the Server

**First time or after stopping:**
```bash
# Docker Compose
docker-compose up -d

# Podman Compose
podman-compose up -d

# Manual script
./scripts/run.sh
```

### Stopping the Server

```bash
# Docker Compose
docker-compose stop

# Podman Compose
podman-compose stop

# Manual command
docker stop bitbucket-mcp
podman stop bitbucket-mcp
```

### Restarting the Server

```bash
# Docker Compose
docker-compose restart

# Podman Compose
podman-compose restart

# Manual command
docker restart bitbucket-mcp
podman restart bitbucket-mcp
```

### Viewing Logs

**Live logs (follow mode):**
```bash
# Docker Compose
docker-compose logs -f bitbucket-mcp

# Podman Compose
podman-compose logs -f bitbucket-mcp

# Manual command
docker logs -f bitbucket-mcp
podman logs -f bitbucket-mcp

# Press Ctrl+C to stop following
```

**Last 50 lines:**
```bash
docker-compose logs --tail=50 bitbucket-mcp
```

**Logs from the last 5 minutes:**
```bash
docker-compose logs --since=5m bitbucket-mcp
```

### Rebuilding the Container

If you change the Dockerfile or requirements:

```bash
# Rebuild the image
docker-compose build --no-cache

# Then restart the container
docker-compose up -d

# Or as one command
docker-compose up -d --build
```

### Executing the MCP Server

The container stays running in the background. To execute the MCP server (e.g., for testing):

```bash
# Using the provided script
./scripts/exec-mcp.sh

# Or manually
docker exec -i bitbucket-mcp python -m src.main --transport stdio --loggers stderr
```

### Removing the Container

If you want to start fresh:

```bash
# Remove the running container
docker-compose down

# Remove the container AND the image
docker-compose down --rmi all

# Manual approach
docker stop bitbucket-mcp
docker rm bitbucket-mcp
```

---

## Configuration Options

### Environment Variables

The `.env` file controls behavior:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BITBUCKET_USERNAME` | Yes | - | Your Bitbucket email address |
| `BITBUCKET_TOKEN` | Yes | - | Your 192-character app password |
| `BITBUCKET_WORKSPACE` | Yes | - | Your Bitbucket workspace name |
| `BITBUCKET_BASE_URL` | No | `https://api.bitbucket.org` | Bitbucket API endpoint |
| `LOG_LEVEL` | No | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR |

### Development vs Production

#### Development Setup

For active development with hot-reload:

```bash
# Use the dev override
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

This configuration:
- Mounts source code volumes (changes auto-reflect)
- Disables automatic restart
- Increases log retention for debugging
- Allocates more resources

**Development docker-compose.dev.yml:**
```yaml
version: '3.8'

services:
  bitbucket-mcp:
    volumes:
      - ./src:/app/src:rw
      - ./configs:/app/configs:rw
    restart: "no"
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"
```

#### Production Setup

For reliable production deployment:

```bash
# Use the prod override
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

This configuration:
- Read-only filesystem for security
- Reduced resource limits
- Shorter health check intervals
- Stricter monitoring

**Production docker-compose.prod.yml:**
```yaml
services:
  bitbucket-mcp:
    read_only: true
    tmpfs:
      - /tmp
    resources:
      limits:
        cpus: '0.5'
        memory: 256M
      reservations:
        cpus: '0.25'
        memory: 128M
    healthcheck:
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 10s
```

### Resource Limits

In the base `docker-compose.yml`, resources are limited:

```yaml
deploy:
  resources:
    limits:
      cpus: '1'
      memory: 512M
    reservations:
      cpus: '0.5'
      memory: 256M
```

Adjust these for your system:

**For low-resource systems (VPS, old computers):**
```yaml
deploy:
  resources:
    limits:
      cpus: '0.5'
      memory: 256M
    reservations:
      cpus: '0.25'
      memory: 128M
```

**For powerful systems:**
```yaml
deploy:
  resources:
    limits:
      cpus: '2'
      memory: 1024M
    reservations:
      cpus: '1'
      memory: 512M
```

### Logging Configuration

Adjust log rotation in `docker-compose.yml`:

```yaml
logging:
  driver: json-file
  options:
    max-size: '10m'    # Max file size
    max-file: '3'      # Number of files to keep
```

Options:
- `max-size`: File size before rotation (100m, 1g, etc.)
- `max-file`: Number of rotated logs to keep
- Set `max-file: '1'` to keep only current logs

---

## Health Checks and Monitoring

### Built-in Health Check

The container includes a health check that verifies environment variables:

```yaml
healthcheck:
  test:
    - CMD
    - sh
    - -c
    - 'test -n "$BITBUCKET_BASE_URL" && test -n "$BITBUCKET_USERNAME" && test -n "$BITBUCKET_PASSWORD"'
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 10s
```

This checks every 30 seconds that credentials are set.

### Checking Health Status

```bash
# Check if container is healthy
docker-compose ps

# Should show: (healthy) or (unhealthy)

# Get detailed health info
docker inspect bitbucket-mcp --format='{{.State.Health.Status}}'

# View health check history
docker inspect bitbucket-mcp --format='{{json .State.Health.Log}}' | jq '.'
```

### Manual Health Verification

```bash
# Check environment variables are present
docker exec bitbucket-mcp env | grep BITBUCKET

# Should output:
# BITBUCKET_USERNAME=your-email@example.com
# BITBUCKET_TOKEN=...
# BITBUCKET_WORKSPACE=...
```

### Monitoring Container Resources

```bash
# Real-time resource usage
docker stats bitbucket-mcp

# Shows: CPU%, Memory, Network I/O

# One-time snapshot
docker stats --no-stream bitbucket-mcp
```

---

## Troubleshooting by Platform

### macOS

#### Docker Desktop Not Running

```bash
# Start Docker Desktop
open -a Docker

# Verify it's running
docker ps

# If you get "Cannot connect to Docker daemon"
# Try restarting Docker
```

#### Permission Denied

```bash
# If you see "Permission denied while trying to connect to Docker daemon"
# Add your user to the docker group
sudo dscl . -append /Groups/docker GroupMembership $(whoami)

# Or use sudo
sudo docker-compose up -d
```

#### Slow Performance

Docker on macOS (Intel) uses virtualization which can be slow. For better performance:

1. Increase Docker Desktop memory:
   - Docker Desktop → Settings → Resources
   - Set Memory to half your total RAM

2. Use native Podman instead:
   ```bash
   brew install podman
   podman-compose up -d
   ```

#### Pod/Service Network Issues

```bash
# Restart Docker Desktop
killall Docker

# Wait a moment
sleep 5

# Restart
open -a Docker

# Wait for it to fully start (check menu bar)
sleep 30

# Try again
docker-compose up -d
```

### Windows

#### Docker Desktop Installation

1. Download [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop)
2. Install with WSL2 backend (recommended)
3. Restart your computer

#### PowerShell Execution Policy

If you get an execution policy error:

```powershell
# Check current policy
Get-ExecutionPolicy

# Allow scripts in current user
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Verify
Get-ExecutionPolicy
```

#### Git Bash vs PowerShell

Git Bash (recommended for Windows):
```bash
# Ensure you're in the project directory
cd /c/path/to/bitbucket-mcp-py

# Run Docker Compose
docker-compose up -d
```

PowerShell:
```powershell
# Set environment variables
$env:BITBUCKET_USERNAME = "your-email@example.com"
$env:BITBUCKET_TOKEN = "your-token"
$env:BITBUCKET_WORKSPACE = "your-workspace"

# OR edit .env file
notepad .env

# Start container
docker-compose up -d
```

#### Hyper-V Issues

If you see "Hyper-V is not installed":

1. Windows 10/11 Pro Edition required for Hyper-V
2. Enable it:
   - Settings → Apps → Apps & features → Programs and Features
   - Click "Turn Windows features on or off"
   - Check "Hyper-V"
   - Restart

3. Or use Podman instead:
   ```powershell
   # Install Podman (requires WSL2)
   choco install podman

   # Use podman-compose instead of docker-compose
   podman-compose up -d
   ```

#### File Path Issues

Windows file paths can cause issues. Use forward slashes or raw strings:

```bash
# Good
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Avoid absolute Windows paths
# Bad: docker-compose -f C:\Users\username\project\docker-compose.yml
```

### Linux

#### Docker Daemon Not Running

```bash
# Start Docker daemon
sudo systemctl start docker

# Enable auto-start
sudo systemctl enable docker

# Verify
sudo systemctl status docker
```

#### Permission Denied

```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Apply group changes (choose one)
newgrp docker
# OR
# Log out and log back in

# Verify
docker ps
```

#### Podman Instead of Docker

```bash
# Install Podman
sudo apt-get install podman podman-compose  # Ubuntu/Debian
sudo dnf install podman podman-compose      # Fedora

# Use podman-compose instead of docker-compose
podman-compose up -d

# If you prefer the docker command
alias docker=podman
```

#### Networking Issues

```bash
# If container can't reach Bitbucket API:

# 1. Check DNS
docker exec bitbucket-mcp nslookup api.bitbucket.org

# 2. Check internet connectivity
docker exec bitbucket-mcp curl -I https://api.bitbucket.org

# 3. Restart docker daemon
sudo systemctl restart docker

# 4. Rebuild container
docker-compose build --no-cache
docker-compose up -d
```

---

## Integration with Claude Desktop/GitHub Copilot

### Claude Desktop Integration

Claude Desktop can execute the MCP server directly from the container.

#### Step 1: Find Your Config File

**macOS/Linux:**
```bash
~/.config/Claude/claude_desktop_config.json
# OR older location
~/Library/Application\ Support/Claude/claude_desktop_config.json
```

**Windows:**
```
%APPDATA%\Claude\claude_desktop_config.json
```

#### Step 2: Ensure Container is Running

```bash
# Start the container first
docker-compose up -d

# Verify it's running
docker-compose ps
```

#### Step 3: Add to Claude Configuration

Edit your `claude_desktop_config.json`:

**For Docker:**
```json
{
  "mcpServers": {
    "bitbucket": {
      "command": "docker",
      "args": [
        "exec",
        "-i",
        "bitbucket-mcp",
        "python",
        "-m",
        "src.main",
        "--transport",
        "stdio",
        "--loggers",
        "stderr"
      ],
      "env": {
        "BITBUCKET_USERNAME": "your-email@example.com",
        "BITBUCKET_TOKEN": "your-192-char-token",
        "BITBUCKET_WORKSPACE": "your-workspace"
      }
    }
  }
}
```

**For Podman:**
```json
{
  "mcpServers": {
    "bitbucket": {
      "command": "podman",
      "args": [
        "exec",
        "-i",
        "bitbucket-mcp",
        "python",
        "-m",
        "src.main",
        "--transport",
        "stdio",
        "--loggers",
        "stderr"
      ],
      "env": {
        "BITBUCKET_USERNAME": "your-email@example.com",
        "BITBUCKET_TOKEN": "your-192-char-token",
        "BITBUCKET_WORKSPACE": "your-workspace"
      }
    }
  }
}
```

#### Step 4: Restart Claude Desktop

Close and reopen Claude Desktop. It should now have access to Bitbucket tools.

#### Security Note

You can omit the `env` section and rely on system environment variables instead:

```json
{
  "mcpServers": {
    "bitbucket": {
      "command": "docker",
      "args": [
        "exec",
        "-i",
        "bitbucket-mcp",
        "python",
        "-m",
        "src.main",
        "--transport",
        "stdio",
        "--loggers",
        "stderr"
      ]
    }
  }
}
```

Then ensure variables are in your shell:
```bash
# macOS/Linux: add to ~/.bashrc or ~/.zshrc
export BITBUCKET_USERNAME="your-email@example.com"
export BITBUCKET_TOKEN="your-192-char-token"
export BITBUCKET_WORKSPACE="your-workspace"

# Windows PowerShell: add to $PROFILE
[Environment]::SetEnvironmentVariable("BITBUCKET_USERNAME", "your-email@example.com", "User")
[Environment]::SetEnvironmentVariable("BITBUCKET_TOKEN", "your-192-char-token", "User")
[Environment]::SetEnvironmentVariable("BITBUCKET_WORKSPACE", "your-workspace", "User")
```

### GitHub Copilot Integration

GitHub Copilot in VS Code can also use the MCP server.

#### Step 1: Locate MCP Config

**macOS:**
```
~/Library/Application Support/Code/User/mcp.json
```

**Windows:**
```
%APPDATA%\Code\User\mcp.json
```

**Linux:**
```
~/.config/Code/User/mcp.json
```

#### Step 2: Create or Edit mcp.json

```json
{
  "mcpServers": {
    "bitbucket-mcp": {
      "command": "docker",
      "args": [
        "exec",
        "-i",
        "bitbucket-mcp",
        "python",
        "-m",
        "src.main",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

#### Step 3: Restart VS Code

Close and reopen VS Code. Copilot should now have access to Bitbucket tools.

---

## Common Issues and Solutions

### Issue: Container exits immediately

**Symptoms:**
```bash
$ docker-compose ps
NAME              STATUS
bitbucket-mcp     Exited (1) 2 seconds ago
```

**Solutions:**

1. Check the logs:
```bash
docker-compose logs bitbucket-mcp
```

2. Most likely cause: missing environment variables
```bash
# Verify .env file exists and has values
cat .env

# Should show:
# BITBUCKET_USERNAME=...
# BITBUCKET_TOKEN=...
# BITBUCKET_WORKSPACE=...
```

3. Rebuild and restart:
```bash
docker-compose build --no-cache
docker-compose up -d
```

### Issue: Authentication errors (401 Unauthorized)

**Symptoms:**
```
Error: Authentication failed (401)
```

**Solutions:**

1. Verify your email is a Bitbucket account email (not workspace name):
```bash
# Check what's in your .env
grep BITBUCKET_USERNAME .env
```

2. Verify token is valid (192 characters):
```bash
# Check token length
grep BITBUCKET_TOKEN .env | wc -c

# Should be 192+ characters
```

3. Verify token has required permissions:
   - Go to [Bitbucket App Passwords](https://bitbucket.org/account/settings/app-passwords/)
   - Check your token has: Repositories (R/W), Pull requests (R/W), Pipelines (R)

4. Test authentication manually:
```bash
docker exec -it bitbucket-mcp python -c "
import asyncio
from src.client import BitbucketClient

async def test():
    client = BitbucketClient(
        'YOUR_EMAIL',
        'YOUR_TOKEN',
        'YOUR_WORKSPACE'
    )
    try:
        user = await client.get_user()
        print('Auth OK:', user)
    except Exception as e:
        print('Auth failed:', e)
    finally:
        await client.close()

asyncio.run(test())
"
```

### Issue: Port already in use

**Symptoms:**
```
Error response from daemon: Ports are not available
```

**Solution:**

The MCP server doesn't use network ports—it uses stdio. If you see this error, you may have another container with the same name:

```bash
# Find and remove any existing container
docker stop bitbucket-mcp 2>/dev/null || true
docker rm bitbucket-mcp 2>/dev/null || true

# Restart
docker-compose up -d
```

### Issue: Out of disk space

**Symptoms:**
```
No space left on device
```

**Solutions:**

1. Clean up old images and containers:
```bash
# Remove stopped containers
docker container prune

# Remove dangling images
docker image prune

# Remove unused volumes
docker volume prune

# See what's using space
docker system df
```

2. Reduce log retention in `docker-compose.yml`:
```yaml
logging:
  driver: json-file
  options:
    max-size: '5m'    # Smaller size
    max-file: '1'     # Keep only current log
```

3. Rebuild:
```bash
docker-compose down
docker-compose build
docker-compose up -d
```

### Issue: Slow performance or memory usage

**Symptoms:**
- Container consuming 100% CPU
- Out of memory errors
- Commands timing out

**Solutions:**

1. Check resource usage:
```bash
docker stats bitbucket-mcp --no-stream
```

2. Increase resource limits in `docker-compose.yml`:
```yaml
deploy:
  resources:
    limits:
      cpus: '2'
      memory: 1024M
    reservations:
      cpus: '1'
      memory: 512M
```

3. Rebuild and restart:
```bash
docker-compose up -d --force-recreate
```

### Issue: Cannot connect to Docker daemon

**Symptoms:**
```
Cannot connect to Docker daemon at unix:///var/run/docker.sock
```

**Solutions:**

**macOS:**
```bash
# Start Docker Desktop
open -a Docker

# Wait for it to start (check menu bar icon)
sleep 30

# Try again
docker ps
```

**Linux:**
```bash
# Start Docker daemon
sudo systemctl start docker

# Enable auto-start
sudo systemctl enable docker

# Add your user to docker group
sudo usermod -aG docker $USER
newgrp docker
```

**Windows:**
```powershell
# Start Docker Desktop
# Or restart PowerShell as Administrator

# Check if it's running
docker ps
```

---

## Advanced Usage

### Custom Docker Compose Configuration

Create a custom override file for your specific needs:

**docker-compose.custom.yml:**
```yaml
version: '3.8'

services:
  bitbucket-mcp:
    # Override anything from the base compose file
    environment:
      - LOG_LEVEL=DEBUG

    # Add volume for persistent data
    volumes:
      - ./data:/app/data:rw

    # Custom network
    networks:
      - custom-network

networks:
  custom-network:
    driver: bridge
```

Run with custom config:
```bash
docker-compose -f docker-compose.yml -f docker-compose.custom.yml up -d
```

### Running Multiple Instances

For multiple workspace instances:

**docker-compose.yml (for workspace1):**
```yaml
version: '3.8'

services:
  bitbucket-mcp-workspace1:
    build:
      context: .
      dockerfile: Dockerfile
    image: bitbucket-mcp-py:latest
    container_name: bitbucket-mcp-workspace1
    env_file:
      - .env.workspace1
    command: tail -f /dev/null
    stdin_open: true
    tty: false
    restart_policy:
      condition: unless-stopped
```

Create separate `.env` files:
```bash
cp env.example .env.workspace1
cp env.example .env.workspace2

# Edit each with different credentials
nano .env.workspace1
nano .env.workspace2
```

Start both:
```bash
docker-compose up -d
```

Execute for specific workspace:
```bash
docker exec -i bitbucket-mcp-workspace1 python -m src.main --transport stdio
docker exec -i bitbucket-mcp-workspace2 python -m src.main --transport stdio
```

### Running with External Network

For multi-container setups (e.g., with other services):

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  bitbucket-mcp:
    # ... rest of config
    networks:
      - shared-network

networks:
  shared-network:
    driver: bridge
    external: false
```

Create before running:
```bash
docker network create shared-network
docker-compose up -d
```

### Persistent Configuration Storage

Store tool configurations persistently:

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  bitbucket-mcp:
    # ... rest of config
    volumes:
      - ./configs:/app/configs:rw
      - config-cache:/app/.cache

volumes:
  config-cache:
    driver: local
```

Your `configs/tools.json` changes persist across restarts.

### Running with System Service (systemd)

Create `/etc/systemd/system/bitbucket-mcp.service`:

```ini
[Unit]
Description=Bitbucket MCP Server
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/bitbucket-mcp-py
ExecStart=/usr/local/bin/docker-compose up
ExecStop=/usr/local/bin/docker-compose down
Restart=unless-stopped
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable bitbucket-mcp
sudo systemctl start bitbucket-mcp

# Check status
sudo systemctl status bitbucket-mcp
```

View logs:
```bash
sudo journalctl -u bitbucket-mcp -f
```

### Docker Compose with Secrets (Production)

For production, use Docker secrets instead of .env files:

**docker-compose.prod.yml:**
```yaml
version: '3.8'

services:
  bitbucket-mcp:
    # ... rest of config
    secrets:
      - bitbucket_token
      - bitbucket_username
    environment:
      - BITBUCKET_TOKEN_FILE=/run/secrets/bitbucket_token
      - BITBUCKET_USERNAME_FILE=/run/secrets/bitbucket_username

secrets:
  bitbucket_token:
    external: true
  bitbucket_username:
    external: true
```

Create secrets:
```bash
echo "your-192-char-token" | docker secret create bitbucket_token -
echo "your-email@example.com" | docker secret create bitbucket_username -
```

Use with Docker Swarm:
```bash
docker stack deploy -c docker-compose.prod.yml bitbucket-mcp
```

### Performance Tuning

For high-throughput scenarios:

**docker-compose.perf.yml:**
```yaml
version: '3.8'

services:
  bitbucket-mcp:
    # More resources for better performance
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 2048M
        reservations:
          cpus: '2'
          memory: 1024M

    # Disable health check for pure performance
    # healthcheck:
    #   disable: true

    # Smaller log rotation for less I/O
    logging:
      driver: json-file
      options:
        max-size: '50m'
        max-file: '2'
```

---

## Quick Reference

### Essential Commands

```bash
# Start
docker-compose up -d

# Stop
docker-compose stop

# Restart
docker-compose restart

# View logs
docker-compose logs -f bitbucket-mcp

# Rebuild
docker-compose build --no-cache

# Full cleanup and restart
docker-compose down
docker-compose build
docker-compose up -d

# Execute MCP server
./scripts/exec-mcp.sh
```

### Verification Checklist

- [ ] `.env` file created and filled with credentials
- [ ] Container builds successfully: `docker-compose build`
- [ ] Container runs: `docker-compose up -d`
- [ ] Container is healthy: `docker-compose ps` shows `(healthy)`
- [ ] Environment variables set: `docker exec bitbucket-mcp env | grep BITBUCKET`
- [ ] MCP server executes: `./scripts/exec-mcp.sh`
- [ ] Claude Desktop can see server (if configured)

---

## Getting Help

If you encounter issues not covered here:

1. **Check logs first:**
   ```bash
   docker-compose logs bitbucket-mcp | tail -50
   ```

2. **Verify credentials:**
   ```bash
   # Email should be your Bitbucket account email
   # Token should be 192 characters
   # Workspace should be your workspace name
   cat .env | grep BITBUCKET
   ```

3. **Test authentication:**
   ```bash
   docker exec -it bitbucket-mcp python -m src.main --transport stdio
   # Type: {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "test"}}}
   # You should see a response (not an error)
   ```

4. **Check Docker daemon:**
   ```bash
   docker ps
   docker system df
   ```

5. **Review project documentation:**
   - Check [README.md](../README.md)
   - See [Dockerfile](../Dockerfile) for build details
   - Review `docker-compose*.yml` files

---

## Next Steps

- [Configure Claude Desktop Integration](#integration-with-claude-desktopgithub-copilot)
- [Explore Advanced Usage](#advanced-usage)
- [Review Available Tools](../README.md#available-mcp-tools)
- [Check Tool Configuration](../README.md#tool-configuration)

---

**Last Updated:** November 2025
**Version:** 1.0.0
