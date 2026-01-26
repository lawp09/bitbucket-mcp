#!/bin/bash

################################################################################
# Container Compose Setup Script for Bitbucket MCP Server
#
# This script automates the setup of container environment (Podman preferred) by:
# - Detecting the operating system
# - Checking for Podman or Docker compose availability (Podman preferred)
# - Creating .env file from env.example
# - Prompting for Bitbucket credentials
# - Building and running containers
# - Verifying the setup
################################################################################

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"
ENV_EXAMPLE="$PROJECT_ROOT/env.example"
DOCKER_COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"

# Variables
OS_TYPE=""
COMPOSE_CMD=""
BITBUCKET_USERNAME=""
BITBUCKET_TOKEN=""
BITBUCKET_WORKSPACE=""

################################################################################
# Utility Functions
################################################################################

print_header() {
    echo -e "\n${CYAN}════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}════════════════════════════════════════════════════════════${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

print_step() {
    echo -e "\n${CYAN}→ $1${NC}"
}

show_help() {
    cat << EOF
${CYAN}Container Compose Setup Script for Bitbucket MCP Server${NC}
${CYAN}(Podman preferred, Docker as fallback)${NC}

${BLUE}Usage:${NC}
    bash compose-setup.sh [OPTIONS]

${BLUE}Options:${NC}
    --help, -h              Show this help message
    --username <email>      Set Bitbucket username (email)
    --token <token>         Set Bitbucket app password
    --workspace <name>      Set Bitbucket workspace name
    --no-build              Skip compose build
    --no-up                 Skip compose up
    --dev                   Use compose.dev.yml instead

${BLUE}Examples:${NC}
    bash compose-setup.sh
    bash compose-setup.sh --username user@example.com --workspace my-workspace
    bash compose-setup.sh --dev

${YELLOW}Note:${NC} For security, use interactive prompts rather than --token flag.

EOF
    exit 0
}

################################################################################
# OS Detection
################################################################################

detect_os() {
    print_step "Detecting operating system"

    case "$(uname -s)" in
        Darwin*)
            OS_TYPE="macOS"
            print_success "macOS detected"
            ;;
        Linux*)
            OS_TYPE="Linux"
            print_success "Linux detected"
            ;;
        MINGW*|MSYS*|CYGWIN*)
            OS_TYPE="Windows"
            print_success "Windows (WSL/Git Bash) detected"
            ;;
        *)
            print_error "Unsupported operating system: $(uname -s)"
            exit 1
            ;;
    esac
}

################################################################################
# Podman/Docker Detection
################################################################################

check_compose_availability() {
    print_step "Checking for Podman Compose / Docker Compose (Podman preferred)"

    # Priority 1: podman compose (Podman v4+ native compose)
    if command -v podman &> /dev/null; then
        if podman compose version &> /dev/null 2>&1; then
            COMPOSE_CMD="podman compose"
            COMPOSE_VERSION=$(podman compose version 2>/dev/null | awk '{print $NF}')
            print_success "Podman (with native compose) found (v$COMPOSE_VERSION)"
            return 0
        fi
    fi

    # Priority 2: podman-compose (standalone podman-compose)
    if command -v podman-compose &> /dev/null; then
        COMPOSE_CMD="podman-compose"
        COMPOSE_VERSION=$(podman-compose --version 2>/dev/null | awk '{print $NF}')
        print_success "podman-compose found (v$COMPOSE_VERSION)"
        return 0
    fi

    # Priority 3: docker compose (Docker compose plugin)
    if command -v docker &> /dev/null; then
        if docker compose version &> /dev/null 2>&1; then
            COMPOSE_CMD="docker compose"
            COMPOSE_VERSION=$(docker compose version 2>/dev/null | awk '{print $NF}')
            print_success "Docker (with compose plugin) found (v$COMPOSE_VERSION)"
            return 0
        fi
    fi

    # Priority 4: docker-compose (standalone docker-compose)
    if command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
        COMPOSE_VERSION=$(docker-compose --version 2>/dev/null | awk '{print $NF}')
        print_success "docker-compose found (v$COMPOSE_VERSION)"
        return 0
    fi

    print_error "No container compose tool found (Podman or Docker)"
    echo -e "${YELLOW}Please install Podman (preferred) or Docker:${NC}"
    echo -e "  Podman (recommended): https://podman.io/docs/installation"
    echo -e "  macOS: brew install podman"
    echo -e "  Linux: apt-get install podman / yum install podman"
    echo -e ""
    echo -e "  Or install Docker as fallback:"
    echo -e "  macOS: brew install docker"
    echo -e "  Linux: apt-get install docker.io / yum install docker"
    exit 1
}

################################################################################
# Environment File Management
################################################################################

create_env_file() {
    if [ -f "$ENV_FILE" ]; then
        print_warning ".env file already exists"
        read -p "Do you want to reconfigure it? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Keeping existing .env file"
            return 0
        fi
    fi

    if [ ! -f "$ENV_EXAMPLE" ]; then
        print_error "env.example file not found at $ENV_EXAMPLE"
        exit 1
    fi

    print_step "Creating .env file from env.example"
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    print_success ".env file created at $ENV_FILE"
}

################################################################################
# Credential Prompts
################################################################################

prompt_credentials() {
    print_step "Configuring Bitbucket credentials"

    # Prompt for username if not provided via flag
    if [ -z "$BITBUCKET_USERNAME" ]; then
        echo -e "${BLUE}Enter your Bitbucket email address:${NC}"
        read -p "  > " BITBUCKET_USERNAME

        if [ -z "$BITBUCKET_USERNAME" ]; then
            print_error "Bitbucket username/email is required"
            exit 1
        fi
    fi

    # Prompt for workspace if not provided via flag
    if [ -z "$BITBUCKET_WORKSPACE" ]; then
        echo -e "${BLUE}Enter your Bitbucket workspace name:${NC}"
        echo -e "  ${YELLOW}(Find it at: https://bitbucket.org/<workspace-name>/)${NC}"
        read -p "  > " BITBUCKET_WORKSPACE

        if [ -z "$BITBUCKET_WORKSPACE" ]; then
            print_error "Bitbucket workspace name is required"
            exit 1
        fi
    fi

    # Prompt for token if not provided via flag
    if [ -z "$BITBUCKET_TOKEN" ]; then
        echo -e "${BLUE}Enter your Bitbucket app password:${NC}"
        echo -e "  ${YELLOW}(Generate at: https://bitbucket.org/account/settings/app-passwords/)${NC}"
        read -sp "  > " BITBUCKET_TOKEN
        echo

        if [ -z "$BITBUCKET_TOKEN" ]; then
            print_error "Bitbucket app password is required"
            exit 1
        fi
    fi

    echo
    print_success "Credentials configured"
}

write_env_file() {
    print_step "Writing credentials to .env file"

    # Create temporary file
    local temp_file="${ENV_FILE}.tmp"

    # Replace environment variables
    sed "s|^BITBUCKET_USERNAME=.*|BITBUCKET_USERNAME=$BITBUCKET_USERNAME|" "$ENV_FILE" > "$temp_file"
    sed -i "s|^BITBUCKET_TOKEN=.*|BITBUCKET_TOKEN=$BITBUCKET_TOKEN|" "$temp_file"
    sed -i "s|^BITBUCKET_WORKSPACE=.*|BITBUCKET_WORKSPACE=$BITBUCKET_WORKSPACE|" "$temp_file"

    # Move temporary file to .env
    mv "$temp_file" "$ENV_FILE"

    print_success "Credentials written to .env file"
}

################################################################################
# Container Operations
################################################################################

build_containers() {
    if [ "$SKIP_BUILD" = true ]; then
        print_info "Skipping compose build (--no-build)"
        return 0
    fi

    print_step "Building containers"

    if ! $COMPOSE_CMD ${COMPOSE_FILE:+-f "$COMPOSE_FILE"} build; then
        print_error "Failed to build containers"
        exit 1
    fi

    print_success "Containers built successfully"
}

start_containers() {
    if [ "$SKIP_UP" = true ]; then
        print_info "Skipping compose up (--no-up)"
        return 0
    fi

    print_step "Starting containers"

    if ! $COMPOSE_CMD ${COMPOSE_FILE:+-f "$COMPOSE_FILE"} up -d; then
        print_error "Failed to start containers"
        exit 1
    fi

    print_success "Containers started in background"
}

show_logs() {
    print_step "Container startup logs (last 10 lines)"

    sleep 2
    echo
    $COMPOSE_CMD ${COMPOSE_FILE:+-f "$COMPOSE_FILE"} logs --tail=10
    echo
}

################################################################################
# Verification
################################################################################

verify_setup() {
    print_step "Verifying setup"

    local container_name="${PROJECT_ROOT##*/}-mcp-server-1"

    # Check if container is running
    if ! $COMPOSE_CMD ${COMPOSE_FILE:+-f "$COMPOSE_FILE"} ps | grep -q "Up"; then
        print_warning "No containers appear to be running"
        return 1
    fi

    print_success "Containers are running"

    # Attempt to verify environment variables
    print_step "Verifying environment variables in container"

    local username_check=$(${COMPOSE_CMD} ${COMPOSE_FILE:+-f "$COMPOSE_FILE"} exec -T mcp-server printenv BITBUCKET_USERNAME 2>/dev/null || echo "")
    local workspace_check=$(${COMPOSE_CMD} ${COMPOSE_FILE:+-f "$COMPOSE_FILE"} exec -T mcp-server printenv BITBUCKET_WORKSPACE 2>/dev/null || echo "")

    if [ -n "$username_check" ] && [ -n "$workspace_check" ]; then
        print_success "Environment variables verified in container"
        return 0
    else
        print_warning "Could not verify environment variables (container may still be initializing)"
        return 0
    fi
}

################################################################################
# Main Setup Flow
################################################################################

main() {
    print_header "Bitbucket MCP Server - Container Setup (Podman preferred)"

    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --help|-h)
                show_help
                ;;
            --username)
                BITBUCKET_USERNAME="$2"
                shift 2
                ;;
            --token)
                BITBUCKET_TOKEN="$2"
                shift 2
                ;;
            --workspace)
                BITBUCKET_WORKSPACE="$2"
                shift 2
                ;;
            --no-build)
                SKIP_BUILD=true
                shift
                ;;
            --no-up)
                SKIP_UP=true
                shift
                ;;
            --dev)
                COMPOSE_FILE="$PROJECT_ROOT/docker-compose.dev.yml"
                shift
                ;;
            *)
                print_error "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done

    # Execute setup steps
    detect_os
    check_compose_availability
    create_env_file
    prompt_credentials
    write_env_file
    build_containers
    start_containers
    show_logs
    verify_setup

    # Print success message
    print_header "Setup Complete!"
    echo -e "${GREEN}The Bitbucket MCP Server is now running.${NC}\n"

    echo -e "${BLUE}Next steps:${NC}"
    echo -e "  1. View logs: ${CYAN}$COMPOSE_CMD ${COMPOSE_FILE:+-f \"$COMPOSE_FILE\"} logs -f${NC}"
    echo -e "  2. Stop containers: ${CYAN}$COMPOSE_CMD ${COMPOSE_FILE:+-f \"$COMPOSE_FILE\"} down${NC}"
    echo -e "  3. Restart containers: ${CYAN}$COMPOSE_CMD ${COMPOSE_FILE:+-f \"$COMPOSE_FILE\"} restart${NC}"
    echo -e "  4. Access shell: ${CYAN}$COMPOSE_CMD ${COMPOSE_FILE:+-f \"$COMPOSE_FILE\"} exec mcp-server bash${NC}"

    echo
    echo -e "${YELLOW}Documentation:${NC}"
    echo -e "  - README: ${CYAN}$PROJECT_ROOT/README.md${NC}"
    echo -e "  - QUICKSTART: ${CYAN}$PROJECT_ROOT/QUICKSTART.md${NC}"
    echo -e "  - Makefile: ${CYAN}$PROJECT_ROOT/Makefile${NC}"

    echo
    print_success "Setup completed successfully!"

    return 0
}

# Run main function
main "$@"
