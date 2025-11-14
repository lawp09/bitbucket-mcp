# Platform Compatibility Guide

This guide covers running the Bitbucket MCP server across different operating systems and container platforms. The server is optimized for container execution with Podman and Docker.

## Supported Platforms

| Platform | Container Runtime | Status | Notes |
|----------|-------------------|--------|-------|
| macOS (Intel/Apple Silicon) | Docker Desktop | ✅ Recommended | Native support via Docker Desktop |
| macOS (Intel/Apple Silicon) | Podman + Lima/Colima | ✅ Fully Supported | Lightweight alternative to Docker Desktop |
| Windows 10/11 | Docker Desktop + WSL2 | ✅ Recommended | Native WSL2 integration required |
| Windows 10/11 | Podman on WSL2 | ✅ Fully Supported | Install Podman inside WSL2 |
| Linux (any distro) | Docker | ✅ Fully Supported | Standard installation |
| Linux (any distro) | Podman (rootless) | ✅ Fully Supported | Recommended for security |
| Linux (any distro) | Podman (root) | ⚠️ Works | Not recommended |

## macOS Setup

### Docker Desktop (Recommended)

**Installation**:
```bash
# Using Homebrew
brew install docker --cask

# Or download from https://www.docker.com/products/docker-desktop
```

**Build and Run**:
```bash
# Build the container
docker build -t bitbucket-mcp-py:latest .

# Run with environment variables
docker run -d \
  --name bitbucket-mcp \
  -e BITBUCKET_USERNAME="your-email@example.com" \
  -e BITBUCKET_TOKEN="your-192-char-token" \
  -e BITBUCKET_WORKSPACE="your-workspace" \
  bitbucket-mcp-py:latest

# Execute MCP server
docker exec -i bitbucket-mcp python -m src.main --transport stdio --loggers stderr
```

**Docker Compose** (Recommended):
```bash
# Copy environment file
cp env.example .env
# Edit .env with your credentials

# Run container
docker compose up -d

# Execute MCP server
docker compose exec bitbucket-mcp python -m src.main --transport stdio --loggers stderr
```

**Claude Desktop Configuration**:
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

### Podman with Lima (macOS)

Lima provides lightweight Linux VMs on macOS, perfect for Podman.

**Installation**:
```bash
# Install Lima
brew install lima

# Initialize Lima with Podman
limactl start --name=default template://podman

# Verify Podman installation
podman --version
```

**Build and Run**:
```bash
# Build the container
podman build -t bitbucket-mcp-py:latest .

# Run with environment variables
podman run -d \
  --name bitbucket-mcp \
  -e BITBUCKET_USERNAME="your-email@example.com" \
  -e BITBUCKET_TOKEN="your-192-char-token" \
  -e BITBUCKET_WORKSPACE="your-workspace" \
  bitbucket-mcp-py:latest

# Execute MCP server
podman exec -i bitbucket-mcp python -m src.main --transport stdio --loggers stderr
```

**Claude Desktop Configuration**:
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
      ]
    }
  }
}
```

### Podman with Colima (macOS)

Colima is a lighter-weight option for running containers on macOS.

**Installation**:
```bash
# Install Colima
brew install colima

# Start Colima with Podman backend
colima start --runtime podman

# Verify Podman installation
podman --version
```

**Build and Run**:
```bash
# Same commands as Lima - Colima is a drop-in replacement
podman build -t bitbucket-mcp-py:latest .
podman run -d --name bitbucket-mcp \
  -e BITBUCKET_USERNAME="your-email@example.com" \
  -e BITBUCKET_TOKEN="your-192-char-token" \
  -e BITBUCKET_WORKSPACE="your-workspace" \
  bitbucket-mcp-py:latest
```

### Path Handling on macOS

**File Mount Issues**:
- Docker Desktop mounts `/Users/` natively
- Lima/Colima mount `/Users/` through FUSE
- Volume paths must use forward slashes: `/path/to/file`

**Example**:
```bash
# Correct - forward slashes
docker run -v /Users/username/config:/app/config ...

# Also correct in docker-compose.yml
volumes:
  - /Users/username/.env:/app/.env
```

### macOS-Specific Issues

**Issue: "Cannot connect to docker daemon"**
```bash
# Ensure Docker Desktop is running
open --app Docker

# Or for Colima
colima start
```

**Issue: "Permission denied" on mounted volumes**
```bash
# Docker Desktop runs as root, check file permissions
ls -la /Users/username/file

# Fix permissions if needed
chmod 644 /Users/username/file
```

**Issue: Out of memory (OOMKilled)**
```bash
# Docker Desktop: Go to Settings → Resources → Memory
# Increase from default (2-4GB is typical)

# Lima/Colima: Edit config or use --memory flag
colima start --memory 4
```

## Windows Setup

### Docker Desktop + WSL2 (Recommended)

**Prerequisites**:
- Windows 10/11 Pro, Enterprise, or Education (Home requires additional setup)
- WSL2 enabled
- Docker Desktop 3.0+

**Installation**:
```powershell
# Using Chocolatey
choco install docker-desktop

# Or download from https://www.docker.com/products/docker-desktop
```

**WSL2 Integration**:
1. Open Docker Desktop
2. Settings → Resources → WSL Integration
3. Enable integration with your WSL2 distributions
4. Apply & Restart

**Build and Run**:
```powershell
# Build the container
docker build -t bitbucket-mcp-py:latest .

# Run with environment variables
docker run -d `
  --name bitbucket-mcp `
  -e BITBUCKET_USERNAME="your-email@example.com" `
  -e BITBUCKET_TOKEN="your-192-char-token" `
  -e BITBUCKET_WORKSPACE="your-workspace" `
  bitbucket-mcp-py:latest

# Execute MCP server
docker exec -i bitbucket-mcp python -m src.main --transport stdio --loggers stderr
```

**Docker Compose**:
```powershell
# Copy environment file
Copy-Item env.example .env

# Edit .env with your credentials

# Run container
docker compose up -d

# Execute MCP server
docker compose exec bitbucket-mcp python -m src.main --transport stdio --loggers stderr
```

### Podman on WSL2

**Installation in WSL2**:
```bash
# Inside WSL2 terminal
sudo apt-get update
sudo apt-get install -y podman

# Verify installation
podman --version
```

**Build and Run**:
```bash
# Same commands as Linux - run inside WSL2 terminal
podman build -t bitbucket-mcp-py:latest .
podman run -d --name bitbucket-mcp \
  -e BITBUCKET_USERNAME="your-email@example.com" \
  -e BITBUCKET_TOKEN="your-192-char-token" \
  -e BITBUCKET_WORKSPACE="your-workspace" \
  bitbucket-mcp-py:latest
```

### Path Handling on Windows

**Critical: Use Forward Slashes**
- Windows paths: `C:\Users\username\project`
- Docker paths: `/c/users/username/project`
- Always use forward slashes in paths

**Docker Compose Volumes**:
```yaml
services:
  bitbucket-mcp:
    volumes:
      # Correct - forward slashes
      - /c/Users/username/.env:/app/.env

      # Wrong - backslashes will fail
      # - C:\Users\username\.env:/app/.env
```

**PowerShell Escape Handling**:
```powershell
# Use backticks for line continuation
docker run -d `
  --name bitbucket-mcp `
  -e BITBUCKET_USERNAME="user@example.com" `
  bitbucket-mcp-py:latest

# Or use single quotes to avoid variable expansion
docker run -d --name bitbucket-mcp `
  -e BITBUCKET_TOKEN='your-actual-token' `
  bitbucket-mcp-py:latest
```

### Credential Storage on Windows

**Option 1: Environment Variables (Recommended)**
```powershell
# Set user environment variables (persistent)
[Environment]::SetEnvironmentVariable("BITBUCKET_USERNAME", "user@example.com", "User")
[Environment]::SetEnvironmentVariable("BITBUCKET_TOKEN", "your-token", "User")
[Environment]::SetEnvironmentVariable("BITBUCKET_WORKSPACE", "workspace", "User")

# Restart PowerShell or IDE for changes to take effect
```

**Option 2: .env File in WSL2**
```bash
# Create .env in project directory (never commit to git)
cat > .env << EOF
BITBUCKET_USERNAME=user@example.com
BITBUCKET_TOKEN=your-token
BITBUCKET_WORKSPACE=workspace
EOF

# Load in docker-compose
docker compose --env-file .env up -d
```

**Option 3: Credential Manager (Advanced)**
```powershell
# Store in Windows Credential Manager
cmdkey /add:bitbucket.org /user:user@example.com /pass:token

# Retrieve in scripts (not recommended for containers)
```

### Windows-Specific Issues

**Issue: "Docker daemon is not running"**
```powershell
# Ensure Docker Desktop is running
# Check system tray or use PowerShell
Get-Process Docker -ErrorAction SilentlyContinue

# Start Docker Desktop
Start-Process "C:\Program Files\Docker\Docker\Docker.exe"
```

**Issue: WSL2 integration not working**
```powershell
# Check WSL2 installation
wsl --list --verbose

# If integration not available, enable in Docker Settings
# Settings → Resources → WSL Integration
```

**Issue: "Cannot find module" or "command not found"**
```powershell
# Ensure you're in the correct directory
Get-Location

# Check file exists
Test-Path -Path ".\docker-compose.yml"

# Build and run from project root
Set-Location -Path "C:\path\to\bitbucket-mcp-py"
docker compose up -d
```

**Issue: Slow file operations**
```powershell
# WSL2 accessing Windows files (/mnt/c/) is slow
# Keep project files in WSL2 filesystem instead
# Clone in: \\wsl$\Ubuntu\home\username\projects

# Or use Docker volume instead of bind mount
docker volume create bitbucket-data
# Reference in docker-compose.yml
```

## Linux Setup

### Docker (Standard)

**Installation** (Ubuntu/Debian):
```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose

# Add user to docker group (optional, avoids sudo)
sudo usermod -aG docker $USER
# Log out and back in for group membership to take effect
```

**Installation** (Fedora/RHEL):
```bash
sudo dnf install -y docker docker-compose

# Enable and start Docker
sudo systemctl enable docker
sudo systemctl start docker

# Add user to docker group (optional)
sudo usermod -aG docker $USER
```

**Build and Run**:
```bash
# Build the container (with or without sudo)
docker build -t bitbucket-mcp-py:latest .

# Run container
docker run -d \
  --name bitbucket-mcp \
  -e BITBUCKET_USERNAME="your-email@example.com" \
  -e BITBUCKET_TOKEN="your-192-char-token" \
  -e BITBUCKET_WORKSPACE="your-workspace" \
  bitbucket-mcp-py:latest

# Execute MCP server
docker exec -i bitbucket-mcp python -m src.main --transport stdio --loggers stderr
```

**Docker Compose**:
```bash
cp env.example .env
# Edit .env with your credentials

docker compose up -d
docker compose exec bitbucket-mcp python -m src.main --transport stdio --loggers stderr
```

### Podman (Recommended for Security)

**Installation** (Ubuntu/Debian):
```bash
sudo apt-get update
sudo apt-get install -y podman podman-compose

# For rootless operation (recommended)
podman system migrate
```

**Installation** (Fedora/RHEL - built-in):
```bash
sudo dnf install -y podman podman-compose
```

**Rootless Mode Setup** (Recommended):
```bash
# Enable current user for rootless Podman
sudo loginctl enable-linger $USER

# Set up user namespace
podman system migrate --new-uid-map-size 65536

# Create subuid/subgid mappings
cat /etc/subuid  # Verify user entry exists
```

**Build and Run (Rootless)**:
```bash
# No sudo needed!
podman build -t bitbucket-mcp-py:latest .

podman run -d \
  --name bitbucket-mcp \
  -e BITBUCKET_USERNAME="your-email@example.com" \
  -e BITBUCKET_TOKEN="your-192-char-token" \
  -e BITBUCKET_WORKSPACE="your-workspace" \
  bitbucket-mcp-py:latest

podman exec -i bitbucket-mcp python -m src.main --transport stdio --loggers stderr
```

**Build and Run (Root - not recommended)**:
```bash
sudo podman build -t bitbucket-mcp-py:latest .
sudo podman run -d --name bitbucket-mcp \
  -e BITBUCKET_USERNAME="your-email@example.com" \
  -e BITBUCKET_TOKEN="your-192-char-token" \
  -e BITBUCKET_WORKSPACE="your-workspace" \
  bitbucket-mcp-py:latest
```

### Volume Permissions on Linux

**Issue: Permission Denied on Mounted Volumes**

```bash
# Container runs as user 1000 (mcpuser)
# Host files must be readable by this user

# Check file ownership
ls -la /path/to/config

# Fix ownership (if you own the file)
chown 1000:1000 /path/to/config

# Or make readable by all (less secure)
chmod 644 /path/to/config

# For directories
chmod 755 /path/to/config/
find /path/to/config -type f -exec chmod 644 {} \;
find /path/to/config -type d -exec chmod 755 {} \;
```

**Docker Compose Volume Handling**:
```yaml
services:
  bitbucket-mcp:
    volumes:
      # Option 1: Named volume (Docker manages permissions)
      - bitbucket-data:/app/data

      # Option 2: Bind mount with user mapping
      - /path/to/config:/app/config:ro  # read-only

volumes:
  bitbucket-data:
    driver: local
```

### SELinux Considerations (Fedora/RHEL)

**Disable SELinux checks for container** (if needed):
```bash
# Temporary - lasts until next boot
sudo setenforce 0

# Permanent - edit /etc/selinux/config
# Set: SELINUX=disabled
# Then reboot
```

**Or allow container access** (more secure):
```bash
# Grant container permission to access volume
sudo chcon -Rt container_file_t /path/to/volume

# Check current context
ls -lZ /path/to/volume
```

**AppArmor on Ubuntu** (if needed):
```bash
# Check if AppArmor is enforcing Docker
sudo aa-status | grep docker

# If issues, restart Docker
sudo systemctl restart docker
```

### Linux-Specific Issues

**Issue: Permission Denied (after docker/podman build)**
```bash
# Ensure user is in docker group
groups $USER

# If not, add and logout/login
sudo usermod -aG docker $USER
newgrp docker

# Or use sudo for single command
sudo docker build -t bitbucket-mcp-py:latest .
```

**Issue: Cannot reach Bitbucket (network issue)**
```bash
# Check container network
docker inspect bitbucket-mcp | grep -A 5 NetworkSettings

# Test connectivity from container
docker exec bitbucket-mcp curl -I https://api.bitbucket.org

# Check firewall
sudo ufw status
# If enabled, allow HTTPS
sudo ufw allow 443
```

**Issue: Out of memory**
```bash
# Check available memory
free -h

# Limit container memory
docker run -d --memory 512m --name bitbucket-mcp bitbucket-mcp-py:latest

# Or in docker-compose.yml
services:
  bitbucket-mcp:
    deploy:
      resources:
        limits:
          memory: 512M
```

## Docker vs Podman Comparison

| Feature | Docker | Podman |
|---------|--------|--------|
| **Architecture** | Daemon-based | Daemonless |
| **Rootless** | Experimental | Native (recommended) |
| **Security** | Good (daemon runs as root) | Excellent (no root daemon) |
| **Compatibility** | Docker Compose support | Podman Compose (good) |
| **Container CLI** | `docker` | `podman` (drop-in replacement) |
| **macOS** | Docker Desktop | Lima/Colima required |
| **Windows** | Docker Desktop | WSL2 required |
| **Linux** | Standard | Recommended |
| **Performance** | High | High (similar) |
| **Resource Usage** | Moderate (daemon overhead) | Lower (daemonless) |
| **Installation** | Larger footprint | Minimal |

### Command Equivalence

```bash
# Docker → Podman (1-to-1 mapping)

# Build
docker build -t image:tag .
podman build -t image:tag .

# Run
docker run -d --name container image
podman run -d --name container image

# Exec
docker exec -i container command
podman exec -i container command

# Compose
docker compose up -d
podman-compose up -d  # or 'podman compose up -d'

# Logs
docker logs container
podman logs container

# List
docker ps
podman ps
```

**Migration from Docker to Podman**:
```bash
# 1. Stop and remove Docker containers
docker compose down

# 2. Install Podman (see platform-specific sections above)

# 3. Run with Podman (commands are identical)
podman compose up -d

# 4. Update Claude Desktop config - change "docker" to "podman"
# Rest of configuration stays the same
```

## Performance Considerations

### macOS Performance

**Docker Desktop**:
- Native performance on Apple Silicon (M1/M2/M3)
- File I/O slower on Intel Macs (FUSE overhead)
- Memory pressure with many containers

**Lima/Colima + Podman**:
- Similar performance to Docker Desktop
- Lower resource overhead
- More control over VM allocation

**Recommendation**: Use Docker Desktop for simplicity, or Colima for lighter resource usage.

### Windows Performance

**Docker Desktop + WSL2**:
- Native performance on Windows 11
- WSL2-to-Windows file access slower
- Keep projects in WSL2 filesystem for best performance

**Path Performance Impact**:
```
Fast:  Files in WSL2 (/home/user/project)
Slow:  Files in Windows (/mnt/c/Users/user/project)
```

**Recommendation**: Store project in WSL2, use Docker/Podman from WSL2 terminal.

### Linux Performance

**Docker**:
- Native Linux performance
- No virtualization overhead
- Fastest option

**Podman (rootless)**:
- Same performance as Docker
- Slightly more overhead in rootless mode (minimal)
- Network performance identical

**Podman (root)**:
- Identical performance to Docker
- Higher security risk

**Recommendation**: Use Podman rootless for best security-to-performance ratio.

## Platform-Specific Troubleshooting

### General Diagnostics

```bash
# Check container status
docker ps -a
# or
podman ps -a

# View container logs
docker logs -f bitbucket-mcp
# or
podman logs -f bitbucket-mcp

# Inspect container configuration
docker inspect bitbucket-mcp
# or
podman inspect bitbucket-mcp

# Check environment variables
docker exec bitbucket-mcp env | grep BITBUCKET
# or
podman exec bitbucket-mcp env | grep BITBUCKET

# Test connectivity
docker exec bitbucket-mcp curl -v https://api.bitbucket.org/2.0/user
# or
podman exec bitbucket-mcp curl -v https://api.bitbucket.org/2.0/user
```

### Network Connectivity

**Test Bitbucket connectivity**:
```bash
# From host machine
curl -u username:token https://api.bitbucket.org/2.0/user

# From container
docker exec -i bitbucket-mcp bash -c \
  'curl -u $BITBUCKET_USERNAME:$BITBUCKET_TOKEN https://api.bitbucket.org/2.0/user'
```

**DNS Resolution Issues**:
```bash
# Check DNS in container
docker exec bitbucket-mcp cat /etc/resolv.conf

# Test DNS resolution
docker exec bitbucket-mcp nslookup api.bitbucket.org

# If DNS fails, check host firewall
# Also verify proxy settings if behind corporate proxy
```

### Resource Monitoring

**Monitor resource usage**:
```bash
# Real-time stats
docker stats bitbucket-mcp
# or
podman stats bitbucket-mcp

# Memory limit enforcement
docker inspect bitbucket-mcp | grep -E 'Memory|MemorySwap'

# Check disk usage
docker system df
# or
podman system df
```

### Container Lifecycle

```bash
# Restart container
docker restart bitbucket-mcp
# or
podman restart bitbucket-mcp

# Stop container
docker stop bitbucket-mcp
# or
podman stop bitbucket-mcp

# Remove container (requires stop first)
docker rm bitbucket-mcp
# or
podman rm bitbucket-mcp

# Prune unused resources
docker system prune
# or
podman system prune
```

## Best Practices

### Security

1. **Never commit credentials to git**
   - Use environment variables
   - Use `.env` files with gitignore
   - Consider credential managers

2. **Run container as non-root**
   - Already configured in Dockerfile (mcpuser, UID 1000)
   - Don't override with root user

3. **Use rootless Podman on Linux**
   - No daemon running as root
   - Better security isolation

4. **Keep base image updated**
   ```bash
   docker pull python:3.12-slim
   docker build --no-cache -t bitbucket-mcp-py:latest .
   ```

### Performance

1. **Use named volumes for data persistence**
   ```yaml
   volumes:
     bitbucket-data:
       driver: local
   ```

2. **Mount configuration files read-only**
   ```bash
   docker run -v /path/to/config:/app/config:ro ...
   ```

3. **Set appropriate resource limits**
   - Default: 512MB memory, 1 CPU
   - Adjust based on your workload

### Maintenance

1. **Regular cleanup**
   ```bash
   docker system prune -a  # Remove unused images
   docker volume prune      # Remove unused volumes
   ```

2. **Monitor logs**
   ```bash
   docker logs --tail 50 -f bitbucket-mcp
   ```

3. **Health checks**
   - Configured in docker-compose.yml
   - Verifies environment variables are set
   - Helps detect configuration issues early

## Additional Resources

- [Docker Documentation](https://docs.docker.com/)
- [Podman Documentation](https://podman.io/docs/)
- [Docker for Mac](https://docs.docker.com/desktop/install/mac-install/)
- [Lima Documentation](https://lima-vm.io/)
- [Colima Documentation](https://github.com/abiosoft/colima)
- [Podman on WSL2](https://github.com/containers/podman/blob/main/docs/tutorials/podman-for-windows.md)
- [SELinux and Containers](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/building_running_and_managing_containers/)

## Platform Support Matrix

| Task | macOS Docker | macOS Podman | Windows Docker | Windows Podman | Linux Docker | Linux Podman |
|------|-------------|--------------|----------------|----------------|--------------|-------------|
| Build | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Run | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Exec | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Volume mounts | ✅ | ✅ | ⚠️ (WSL2 needed) | ⚠️ (WSL2 needed) | ✅ | ✅ |
| Rootless | ❌ | ✅ | ❌ | ✅ (via WSL2) | ❌ | ✅ |
| Native perf | ✅ | ✅ | ⚠️ (WSL2 overhead) | ⚠️ (WSL2 overhead) | ✅ | ✅ |

---

**Last Updated**: 2025-11-07
**Maintainer**: Bitbucket MCP Team
