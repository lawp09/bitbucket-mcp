# Migration Guide: Shell Scripts to Docker Compose

This guide helps you migrate from using individual shell scripts to a streamlined Docker Compose setup for managing the Bitbucket MCP server.

## Why Migrate to Docker Compose?

Docker Compose provides several advantages over shell scripts:

| Aspect | Shell Scripts | Docker Compose |
|--------|---------------|-----------------|
| **Configuration** | Environment variables + manual setup | Single `docker-compose.yml` file |
| **Startup** | Multiple commands needed | One `docker-compose up` |
| **Service Management** | Manual container management | Automatic orchestration |
| **Environment Handling** | `.env` files can be forgotten | Built-in `.env` support |
| **Reproducibility** | Depends on correct env vars | Consistent across machines |
| **Networking** | Manual port/network config | Automatic service discovery |
| **Logs** | Multiple commands needed | Unified log streaming |
| **Cleanup** | Manual removal of containers/images | Automatic with `docker-compose down` |
| **Version Control** | Implicit in scripts | Explicit in `docker-compose.yml` |
| **Team Collaboration** | More configuration sharing needed | Single file ensures consistency |

## Prerequisites Check

Before migrating, verify you have:

```bash
# Check Docker Compose version (v2.0+)
docker-compose --version

# Or if using standalone:
docker compose version

# Verify Docker daemon is running
docker ps

# Check current shell scripts (should see 4 files)
ls -la scripts/
```

Expected output:
- `scripts/build.sh`
- `scripts/run.sh`
- `scripts/exec-mcp.sh`
- `scripts/test.sh`

## Side-by-Side Comparison

### Building the Container

**Old Way (Shell Script)**:
```bash
./scripts/build.sh
```

Script checks:
- Sets up directory paths
- Calls `podman build --no-cache`
- Prints next steps

**New Way (Docker Compose)**:
```bash
docker-compose build
```

Benefits:
- No path management needed
- Consistent with docker-compose.yml
- Automatically uses correct context

---

### Running the Container

**Old Way (Shell Script)**:
```bash
# Set environment variables (one-time, but easy to forget)
export BITBUCKET_USERNAME='your-email@example.com'
export BITBUCKET_TOKEN='your-192-char-token'
export BITBUCKET_WORKSPACE='your-workspace'

# Run container
./scripts/run.sh
```

Script does:
- Validates environment variables
- Stops/removes existing container
- Starts new container with env vars
- Prints status

**New Way (Docker Compose)**:
```bash
# Create .env file once (persists for future runs)
cat > .env << EOF
BITBUCKET_USERNAME=your-email@example.com
BITBUCKET_TOKEN=your-192-char-token
BITBUCKET_WORKSPACE=your-workspace
EOF

# Start container
docker-compose up -d
```

Benefits:
- Environment variables persist in `.env`
- Single command to start all services
- Automatic container cleanup on stop
- Better error messages

---

### Executing the MCP Server

**Old Way (Shell Script)**:
```bash
./scripts/exec-mcp.sh
```

Script does:
- Checks if container is running
- Executes MCP server via `podman exec`
- Pipes stdin for stdio transport

**New Way (Docker Compose)**:
```bash
# Option 1: Direct exec (same as before)
docker-compose exec bitbucket python -m src.main --transport stdio --loggers stderr

# Option 2: Using run (creates temporary container)
docker-compose run --rm bitbucket python -m src.main --transport stdio --loggers stderr
```

---

### Running Tests

**Old Way (Shell Script)**:
```bash
./scripts/test.sh
```

Script does:
- Sets up Python path
- Runs pytest with coverage
- Reports results

**New Way (Docker Compose)**:
```bash
# Run tests in container
docker-compose run --rm bitbucket pytest tests/ -v --cov=src --cov-report=term-missing

# Or locally (if Python 3.12+ installed)
pytest tests/ -v --cov=src --cov-report=term-missing
```

## Step-by-Step Migration

### Step 1: Create Docker Compose File

Create `docker-compose.yml` in your project root:

```yaml
version: '3.8'

services:
  bitbucket:
    build:
      context: .
      dockerfile: Dockerfile
    image: bitbucket-mcp-py:latest
    container_name: bitbucket-mcp
    environment:
      - BITBUCKET_USERNAME=${BITBUCKET_USERNAME}
      - BITBUCKET_TOKEN=${BITBUCKET_TOKEN}
      - BITBUCKET_WORKSPACE=${BITBUCKET_WORKSPACE}
    env_file:
      - .env
    command: tail -f /dev/null
    restart: unless-stopped
```

**Copy-paste ready**:
```bash
cp docker-compose.yml.example docker-compose.yml
```

### Step 2: Create Environment File

Create `.env` file in your project root:

```bash
cat > .env << 'EOF'
BITBUCKET_USERNAME=your-email@example.com
BITBUCKET_TOKEN=your-192-char-token
BITBUCKET_WORKSPACE=your-workspace
EOF
```

**Important**: Add to `.gitignore` to prevent credential leaks:

```bash
echo ".env" >> .gitignore
echo ".env.*.local" >> .gitignore
```

### Step 3: Update Your Shell Configuration (Optional)

If you prefer environment variables for other tools, keep them in your shell:

**macOS/Linux** (add to `~/.bashrc` or `~/.zshrc`):
```bash
export BITBUCKET_USERNAME="your-email@example.com"
export BITBUCKET_TOKEN="your-192-char-app-password"
export BITBUCKET_WORKSPACE="your-workspace-name"
```

Then reload:
```bash
source ~/.bashrc  # or ~/.zshrc
```

Docker Compose will use these variables automatically if `.env` doesn't exist.

### Step 4: Verify Docker Compose Setup

Test that everything is configured correctly:

```bash
# Validate compose file
docker-compose config

# Expected output: Full YAML with all variables expanded
```

### Step 5: Build the Container

```bash
# Build image
docker-compose build

# Expected output:
# => docker build ...
# [+] Building ...
# => exporting to image ...
# => => naming to docker.io/library/bitbucket-mcp-py:latest
```

### Step 6: Start the Container

```bash
# Start services in background
docker-compose up -d

# Expected output:
# [+] Running 1/1
#  ✔ bitbucket Started
```

### Step 7: Verify Container is Running

```bash
# Check status
docker-compose ps

# Expected output:
# NAME                STATUS              PORTS
# bitbucket-mcp       Up 2 seconds
```

### Step 8: Test MCP Server Execution

```bash
# Execute MCP server (same as ./scripts/exec-mcp.sh)
docker-compose exec bitbucket python -m src.main --transport stdio --loggers stderr

# Should start without errors (Ctrl+C to exit)
```

### Step 9: Update MCP Client Configuration

Update your Claude Desktop or GitHub Copilot configuration:

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "bitbucket": {
      "command": "docker-compose",
      "args": [
        "exec",
        "bitbucket",
        "python",
        "-m",
        "src.main",
        "--transport",
        "stdio",
        "--loggers",
        "stderr"
      ],
      "cwd": "/path/to/bitbucket-mcp-py"
    }
  }
}
```

**GitHub Copilot** (`~/.config/Code/User/mcp.json`):

```json
{
  "mcpServers": {
    "bitbucket-mcp": {
      "command": "docker-compose",
      "args": [
        "exec",
        "bitbucket",
        "python",
        "-m",
        "src.main",
        "--transport",
        "stdio"
      ],
      "cwd": "/path/to/bitbucket-mcp-py"
    }
  }
}
```

### Step 10: Verify Everything Works

```bash
# Check container logs
docker-compose logs -f

# Test a simple API call
docker-compose exec bitbucket python -c "
import asyncio
from src.client import BitbucketClient

async def test():
    client = BitbucketClient(
        'BITBUCKET_USERNAME',
        'BITBUCKET_TOKEN',
        'BITBUCKET_WORKSPACE'
    )
    user = await client.get_user()
    print(f'Authenticated as: {user}')
    await client.close()

asyncio.run(test())
"
```

## Keeping Both Approaches (Temporary)

During transition, you can run both setups:

```bash
# Keep old scripts working
./scripts/build.sh
./scripts/run.sh

# Also prepare Docker Compose
docker-compose build
docker-compose up -d -f docker-compose.dev.yml
```

**Prevent naming conflicts**:

```bash
# Use different container names
docker-compose -f docker-compose.yml -p compose_version up -d
docker run --name script_version ...
```

**View both**:
```bash
docker ps -a
```

## What to Do with Old Scripts

### Option 1: Archive Scripts

Keep them for reference but mark as deprecated:

```bash
mkdir -p scripts/deprecated
mv scripts/build.sh scripts/deprecated/
mv scripts/run.sh scripts/deprecated/
mv scripts/exec-mcp.sh scripts/deprecated/
mv scripts/test.sh scripts/deprecated/

# Create README for deprecated scripts
cat > scripts/deprecated/README.md << 'EOF'
# Deprecated Scripts

These shell scripts have been replaced by Docker Compose.

Use `docker-compose` commands instead:
- Build: `docker-compose build`
- Run: `docker-compose up -d`
- Exec: `docker-compose exec bitbucket python -m src.main ...`
- Test: `docker-compose run --rm bitbucket pytest ...`

See `/MIGRATION_GUIDE.md` for details.
EOF
```

### Option 2: Remove Scripts Entirely

If fully migrating:

```bash
rm scripts/build.sh scripts/run.sh scripts/exec-mcp.sh scripts/test.sh

# Verify only test.sh if needed for CI/CD
ls scripts/
```

### Option 3: Update Scripts to Use Docker Compose

Make scripts wrappers around docker-compose:

```bash
# scripts/build.sh (updated)
#!/bin/bash
set -e
docker-compose build

# scripts/run.sh (updated)
#!/bin/bash
set -e
docker-compose up -d

# scripts/exec-mcp.sh (updated)
#!/bin/bash
set -e
docker-compose exec bitbucket python -m src.main --transport stdio --loggers stderr
```

## Troubleshooting Migration Issues

### Issue: `.env` File Not Being Loaded

**Problem**: Variables not expanding in docker-compose

**Solution**:
```bash
# Verify .env file exists
ls -la .env

# Check file format (no extra spaces)
cat .env

# Validate compose file
docker-compose config

# If still not working, verify .env is in project root
pwd
```

---

### Issue: Container Won't Start

**Problem**: `docker-compose up` fails

**Diagnosis**:
```bash
# Check build logs
docker-compose build --no-cache

# View detailed logs
docker-compose logs bitbucket

# Validate compose syntax
docker-compose config
```

**Common causes**:
- Missing `Dockerfile`
- Invalid YAML in `docker-compose.yml`
- Docker daemon not running

---

### Issue: MCP Server Not Responding

**Problem**: `docker-compose exec` hangs or fails

**Diagnosis**:
```bash
# Verify container is running
docker-compose ps

# Check if service started
docker-compose logs bitbucket

# Try manual exec
docker-compose exec bitbucket python -m src.main --help

# Verify environment variables
docker-compose exec bitbucket env | grep BITBUCKET
```

---

### Issue: Permission Denied

**Problem**: `docker-compose` command fails with permissions

**Solution**:
```bash
# Option 1: Add current user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Option 2: Use sudo
sudo docker-compose up -d

# Option 3: Check docker socket permissions
ls -la /var/run/docker.sock
```

---

### Issue: Previous Container Interferes

**Problem**: Old container still running from shell scripts

**Solution**:
```bash
# List all containers
docker ps -a

# Stop old container
docker stop bitbucket-mcp
docker rm bitbucket-mcp

# Or stop via script
./scripts/run.sh  # (old script stops existing)

# Then use docker-compose
docker-compose up -d
```

---

### Issue: Environment Variables Not Set

**Problem**: `BITBUCKET_*` vars not available in container

**Solution**:
```bash
# Verify .env file
cat .env

# Verify docker-compose.yml references .env
grep -A 2 "env_file:" docker-compose.yml

# Explicitly set on command line
docker-compose up -d --build --set BITBUCKET_USERNAME=you@email.com

# Or in docker-compose.yml
services:
  bitbucket:
    environment:
      BITBUCKET_USERNAME: "your@email.com"  # (not recommended, use .env)
```

## Rollback Instructions

If you need to revert to shell scripts:

### Quick Rollback

```bash
# Stop docker-compose services
docker-compose down

# Restore shell scripts (if archived)
cp scripts/deprecated/*.sh scripts/

# Make executable
chmod +x scripts/*.sh

# Set environment variables
export BITBUCKET_USERNAME='your-email@example.com'
export BITBUCKET_TOKEN='your-192-char-token'
export BITBUCKET_WORKSPACE='your-workspace'

# Run using old script
./scripts/build.sh
./scripts/run.sh
```

### Complete Cleanup

```bash
# Stop and remove compose containers
docker-compose down -v

# Remove images
docker-compose down --rmi all

# Remove docker-compose.yml and .env
rm docker-compose.yml
rm .env

# Restore shell scripts
git restore scripts/build.sh scripts/run.sh scripts/exec-mcp.sh scripts/test.sh
```

### Keep Docker Image

```bash
# If you want to keep the built image but stop using compose:
docker-compose down

# Image remains for manual use
docker images | grep bitbucket-mcp
```

## Quick Reference

### Common Docker Compose Commands

```bash
# Lifecycle
docker-compose up -d          # Start services
docker-compose down           # Stop and remove containers
docker-compose restart        # Restart services
docker-compose stop           # Stop without removing
docker-compose start          # Start without rebuilding

# Building and Images
docker-compose build          # Build images
docker-compose build --no-cache  # Rebuild from scratch
docker-compose pull           # Pull pre-built images

# Execution
docker-compose exec SERVICE CMD     # Run in running container
docker-compose run --rm SERVICE CMD # Run in new container

# Inspection
docker-compose ps             # Show running services
docker-compose logs           # Show logs
docker-compose logs -f        # Follow logs
docker-compose config         # Validate and show config

# Maintenance
docker-compose rm             # Remove stopped containers
docker-compose prune          # Remove unused resources
docker-compose down -v        # Remove containers and volumes
```

### Migration Checklist

- [ ] Verify Docker Compose installed (`docker-compose --version`)
- [ ] Create `docker-compose.yml` file
- [ ] Create `.env` file with credentials
- [ ] Add `.env` to `.gitignore`
- [ ] Build with `docker-compose build`
- [ ] Start with `docker-compose up -d`
- [ ] Verify with `docker-compose ps`
- [ ] Test with `docker-compose exec bitbucket python -m src.main ...`
- [ ] Update MCP client config (Claude Desktop/Copilot)
- [ ] Test MCP server in client
- [ ] Archive or remove old shell scripts
- [ ] Commit `docker-compose.yml` to git
- [ ] Document new workflow for team

## Need Help?

### Check Container Logs

```bash
docker-compose logs -f bitbucket
```

### Validate Configuration

```bash
docker-compose config
```

### Test Connectivity

```bash
docker-compose exec bitbucket curl -X GET https://api.bitbucket.org/2.0/user \
  -H "Authorization: Basic $(echo -n 'user:token' | base64)"
```

### Full Restart

```bash
docker-compose down -v
docker-compose up -d --build
```

---

**Last Updated**: 2025-11-07
**Version**: 1.0
**For Issues**: Check project repository or documentation
