#!/bin/bash

#===============================================================================
# Kali Agent Installation Script
# 
# This script installs the Kali Agent security assistant and its dependencies
# on Kali Linux or Debian-based systems.
#
# Usage: sudo ./install.sh
#===============================================================================

set -e  # Exit on error

#-------------------------------------------------------------------------------
# Color Definitions
#-------------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

#-------------------------------------------------------------------------------
# Helper Functions
#-------------------------------------------------------------------------------

print_banner() {
    echo -e "${CYAN}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║                    KALI AGENT INSTALLER                       ║"
    echo "║              AI-Powered Security Assistant                    ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "\n${BOLD}${CYAN}==>${NC} ${BOLD}$1${NC}\n"
}

check_command() {
    if ! command -v "$1" &> /dev/null; then
        return 1
    fi
    return 0
}

prompt_input() {
    local prompt="$1"
    local var_name="$2"
    local is_secret="${3:-false}"
    
    if [ "$is_secret" = "true" ]; then
        echo -e -n "${YELLOW}$prompt: ${NC}"
        read -rs "$var_name"
        echo
    else
        echo -e -n "${YELLOW}$prompt: ${NC}"
        read -r "$var_name"
    fi
}

prompt_confirm() {
    local prompt="$1"
    local default="${2:-n}"
    local response
    
    if [ "$default" = "y" ]; then
        echo -e -n "${YELLOW}$prompt [Y/n]: ${NC}"
    else
        echo -e -n "${YELLOW}$prompt [y/N]: ${NC}"
    fi
    
    read -r response
    response=${response:-$default}
    
    [[ "$response" =~ ^[Yy]$ ]]
}

error_exit() {
    log_error "$1"
    exit 1
}

#-------------------------------------------------------------------------------
# Pre-flight Checks
#-------------------------------------------------------------------------------

check_root() {
    if [[ $EUID -ne 0 ]]; then
        error_exit "This script must be run as root. Use: sudo ./install.sh"
    fi
}

check_os() {
    log_step "Checking operating system compatibility..."
    
    if [[ ! -f /etc/os-release ]]; then
        error_exit "Cannot detect operating system. /etc/os-release not found."
    fi
    
    source /etc/os-release
    
    if [[ "$ID" != "kali" && "$ID" != "debian" && "$ID_LIKE" != *"debian"* ]]; then
        log_warning "This script is designed for Kali Linux or Debian-based systems."
        log_warning "Detected OS: $PRETTY_NAME"
        if ! prompt_confirm "Continue anyway?" "n"; then
            error_exit "Installation cancelled by user."
        fi
    else
        log_success "Detected compatible OS: $PRETTY_NAME"
    fi
}

check_python_version() {
    log_step "Checking Python version..."
    
    if ! command -v python3 &> /dev/null; then
        error_exit "python3 not found. Please install Python 3.11 or higher."
    fi
    
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    PYTHON_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
    PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
    log_info "Detected Python $PYTHON_VERSION"

    if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
        log_error "Python 3.11+ required. Found $PYTHON_VERSION"
        exit 1
    fi

    log_success "Python version $PYTHON_VERSION is compatible"
}

#-------------------------------------------------------------------------------
# Installation Functions
#-------------------------------------------------------------------------------

install_dependencies() {
    log_step "Installing system dependencies..."
    
    local packages=(
        python3
        python3-venv
        python3-full
        redis-server
        nmap
        gobuster
        nuclei
        nikto
        sqlmap
        subfinder
        feroxbuster
        whatweb
        ffuf
    )
    
    log_info "Updating package lists..."
    apt update -qq || error_exit "Failed to update package lists."
    
    log_info "Installing packages: ${packages[*]}"
    
    local failed_packages=()
    
    for package in "${packages[@]}"; do
        log_info "Installing $package..."
        if ! apt install -y -qq "$package" 2>/dev/null; then
            log_warning "Failed to install $package, attempting to continue..."
            failed_packages+=("$package")
        fi
    done
    
    if [ ${#failed_packages[@]} -gt 0 ]; then
        log_warning "The following packages could not be installed: ${failed_packages[*]}"
        log_warning "Some features may not work correctly."
    else
        log_success "All packages installed successfully."
    fi
}

setup_redis() {
    log_step "Configuring Redis..."
    
    if systemctl is-active --quiet redis-server; then
        log_success "Redis is already running."
    else
        log_info "Starting Redis server..."
        systemctl enable redis-server >/dev/null 2>&1
        systemctl start redis-server || error_exit "Failed to start Redis."
        log_success "Redis server started and enabled."
    fi
}

setup_directory() {
    log_step "Setting up installation directory..."
    
    INSTALL_DIR="/opt/kali-agent"
    
    if [[ -d "$INSTALL_DIR" ]]; then
        log_warning "Directory $INSTALL_DIR already exists."
        if prompt_confirm "Remove existing installation?" "n"; then
            rm -rf "$INSTALL_DIR"
            log_info "Removed existing installation."
        fi
    fi
    
    mkdir -p "$INSTALL_DIR"
    log_success "Created directory: $INSTALL_DIR"
}

copy_project_files() {
    log_step "Copying project files..."
    
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    
    # List of directories and files to copy
    local items=(
        "daemon.py"
        "requirements.txt"
        "kali-agent.service"
        "agent"
        "bot"
        "config"
        "skills"
        "store"
        "tasks"
    )
    
    for item in "${items[@]}"; do
        local src="$SCRIPT_DIR/$item"
        local dest="$INSTALL_DIR/$item"
        
        if [[ -e "$src" ]]; then
            if [[ -d "$src" ]]; then
                cp -r "$src" "$dest"
            else
                cp "$src" "$dest"
            fi
            log_info "Copied: $item"
        else
            log_warning "Source not found, skipping: $item"
        fi
    done
    
    log_success "Project files copied to $INSTALL_DIR"
}

create_virtualenv() {
    log_step "Creating Python virtual environment..."
    
    cd "$INSTALL_DIR"
    
    if [[ -d ".venv" ]]; then
        log_info "Removing existing virtual environment..."
        rm -rf .venv
    fi
    
    log_info "Creating virtual environment..."
    python3 -m venv .venv || error_exit "Failed to create virtual environment."
    
    log_info "Upgrading pip..."
    .venv/bin/pip install --upgrade pip -q
    
    log_info "Installing requirements..."
    if [[ -f "requirements.txt" ]]; then
        .venv/bin/pip install -r requirements.txt -q || error_exit "Failed to install Python requirements."
    else
        error_exit "requirements.txt not found."
    fi
    
    log_success "Virtual environment created and dependencies installed."
}

configure_environment() {
    log_step "Configuring environment variables..."
    
    ENV_FILE="$INSTALL_DIR/.env"
    
    # Check if .env already exists
    if [[ -f "$ENV_FILE" ]]; then
        log_warning ".env file already exists."
        if ! prompt_confirm "Overwrite existing configuration?" "n"; then
            log_info "Keeping existing .env file."
            return
        fi
    fi
    
    echo -e "\n${CYAN}Please provide the following configuration values:${NC}\n"
    
    # Prompt for API key
    while true; do
        prompt_input "Enter your ZAI_API_KEY" ZAI_API_KEY "true"
        if [[ -n "$ZAI_API_KEY" ]]; then
            break
        fi
        log_error "API key cannot be empty."
    done
    
    # Prompt for Telegram bot token
    while true; do
        prompt_input "Enter your TELEGRAM_BOT_TOKEN" TELEGRAM_BOT_TOKEN "true"
        if [[ -n "$TELEGRAM_BOT_TOKEN" ]]; then
            break
        fi
        log_error "Bot token cannot be empty."
    done
    
    # Write .env file
    cat > "$ENV_FILE" << EOF
# Kali Agent Environment Configuration
# Generated on $(date)

ZAI_API_KEY=${ZAI_API_KEY}
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
PYTHONUNBUFFERED=1
EOF
    
    chmod 600 "$ENV_FILE"
    log_success ".env file created with your configuration."
}

configure_telegram_user() {
    log_step "Configuring Telegram authorized user..."
    
    SETTINGS_FILE="$INSTALL_DIR/config/settings.yaml"
    
    if [[ ! -f "$SETTINGS_FILE" ]]; then
        log_warning "settings.yaml not found, skipping Telegram user configuration."
        return
    fi
    
    echo -e "\n${CYAN}Telegram User Configuration${NC}"
    echo -e "Enter your Telegram user ID to restrict bot access."
    echo -e "You can get your user ID by messaging @userinfobot on Telegram.\n"
    
    prompt_input "Enter your Telegram user ID (or press Enter to skip)" TELEGRAM_USER_ID
    
    if [[ -n "$TELEGRAM_USER_ID" ]]; then
        # Update settings.yaml with the user ID
        if grep -q "authorized_users:" "$SETTINGS_FILE"; then
            # Update existing authorized_users
            sed -i "s/authorized_users:.*/authorized_users: [$TELEGRAM_USER_ID]/" "$SETTINGS_FILE"
        else
            # Add authorized_users if it doesn't exist
            echo "authorized_users: [$TELEGRAM_USER_ID]" >> "$SETTINGS_FILE"
        fi
        log_success "Telegram user ID configured."
    else
        log_info "Skipping Telegram user configuration."
    fi
}

setup_systemd_service() {
    log_step "Setting up systemd service..."
    
    SERVICE_FILE="$INSTALL_DIR/kali-agent.service"
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    
    # Copy service file if it exists in the script directory
    if [[ -f "$SCRIPT_DIR/kali-agent.service" ]]; then
        cp "$SCRIPT_DIR/kali-agent.service" "$SERVICE_FILE"
    fi
    
    # Fallback: generate service file inline if still missing
    if [[ ! -f "$SERVICE_FILE" ]]; then
        log_warning "kali-agent.service not found, generating inline..."
        cat > "$SERVICE_FILE" << 'EOF'
[Unit]
Description=Kali Agent - AI-powered security assistant
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/kali-agent
EnvironmentFile=/opt/kali-agent/.env
ExecStart=/opt/kali-agent/.venv/bin/python /opt/kali-agent/daemon.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
        log_info "Generated kali-agent.service inline."
    fi
    
    # Copy service file to systemd
    cp "$SERVICE_FILE" /etc/systemd/system/kali-agent.service
    
    # Reload systemd daemon
    systemctl daemon-reload
    
    # Enable the service
    systemctl enable kali-agent.service >/dev/null 2>&1
    
    log_success "Systemd service installed and enabled."
}

start_service() {
    log_step "Starting Kali Agent service..."
    
    # Start the service
    if systemctl start kali-agent.service; then
        log_success "Service started successfully."
    else
        log_error "Failed to start service."
        log_info "Check logs with: journalctl -u kali-agent -n 50"
        return 1
    fi
    
    # Wait a moment for the service to initialize
    sleep 2
    
    # Show service status
    echo -e "\n${CYAN}Service Status:${NC}"
    systemctl status kali-agent.service --no-pager || true
    
    # Show recent logs
    echo -e "\n${CYAN}Recent Logs:${NC}"
    journalctl -u kali-agent -n 20 --no-pager || true
}

print_summary() {
    echo -e "\n"
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║              INSTALLATION COMPLETE                            ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo -e "\n${BOLD}Installation Directory:${NC} $INSTALL_DIR"
    echo -e "${BOLD}Configuration File:${NC} $INSTALL_DIR/.env"
    echo -e "${BOLD}Service Name:${NC} kali-agent"
    echo -e "\n${CYAN}Useful Commands:${NC}"
    echo -e "  ${BOLD}Check status:${NC}  systemctl status kali-agent"
    echo -e "  ${BOLD}View logs:${NC}     journalctl -u kali-agent -f"
    echo -e "  ${BOLD}Restart:${NC}       systemctl restart kali-agent"
    echo -e "  ${BOLD}Stop:${NC}          systemctl stop kali-agent"
    echo -e ""
}

#-------------------------------------------------------------------------------
# Main Installation Flow
#-------------------------------------------------------------------------------

main() {
    print_banner
    
    # Pre-flight checks
    check_root
    check_os
    check_python_version
    
    # Installation steps
    install_dependencies
    setup_redis
    setup_directory
    copy_project_files
    create_virtualenv
    configure_environment
    configure_telegram_user
    setup_systemd_service
    start_service
    print_summary
}

# Run main function
main "$@"
