#!/usr/bin/env bash
# Posipaka — One-command VPS deployment
# Usage: curl -sSL https://raw.githubusercontent.com/0502srv/posipaka/main/scripts/deploy.sh | bash
# Or:    bash scripts/deploy.sh
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'; BOLD='\033[1m'

REPO_URL="${POSIPAKA_REPO:-https://github.com/0502srv/posipaka.git}"
INSTALL_DIR="${POSIPAKA_DIR:-/opt/posipaka}"
DATA_DIR="${POSIPAKA_DATA:-$HOME/.posipaka}"

log() { echo -e "${BLUE}[posipaka]${NC} $*"; }
ok()  { echo -e "${GREEN}[posipaka]${NC} $*"; }
err() { echo -e "${RED}[posipaka]${NC} $*" >&2; }

# ─── Detect if sudo is needed for docker ────────────────────────────────────
DOCKER=""
_detect_docker() {
    if command -v docker &>/dev/null; then
        if docker info &>/dev/null 2>&1; then
            DOCKER="docker"
        elif sudo docker info &>/dev/null 2>&1; then
            DOCKER="sudo docker"
        fi
    fi
}

# ─── Banner ──────────────────────────────────────────────────────────────────
echo -e "${BLUE}${BOLD}"
cat << 'BANNER'
  ____           _             _
 |  _ \ ___  ___(_)_ __   __ _| | ____ _
 | |_) / _ \/ __| | '_ \ / _` | |/ / _` |
 |  __/ (_) \__ \ | |_) | (_| |   < (_| |
 |_|   \___/|___/_| .__/ \__,_|_|\_\__,_|
                   |_|  VPS Deploy
BANNER
echo -e "${NC}"

# ─── Detect deploy method ───────────────────────────────────────────────────
_detect_docker
if [[ -n "$DOCKER" ]]; then
    DEPLOY_METHOD="docker"
    log "Docker detected — using Docker Compose deployment"
else
    DEPLOY_METHOD="native"
    log "No Docker — using native Python deployment"
fi

# ─── Clone or update repo ───────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    log "Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull origin main --ff-only
else
    log "Cloning repository..."
    sudo mkdir -p "$INSTALL_DIR"
    sudo chown "$(whoami):$(whoami)" "$INSTALL_DIR"
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ─── Create data dir ────────────────────────────────────────────────────────
mkdir -p "$DATA_DIR"

# ─── Setup .env if missing ──────────────────────────────────────────────────
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
fi

# ─── Interactive config ──────────────────────────────────────────────────────
_current_key=$(grep "^LLM_API_KEY=" "$INSTALL_DIR/.env" | cut -d= -f2-)
if [[ "$_current_key" == "sk-ant-your-key-here" || "$_current_key" == "your-api-key-here" || -z "$_current_key" ]]; then
    echo ""
    echo -e "${YELLOW}${BOLD}Configuration${NC}"
    echo ""

    # LLM Provider
    echo -e "${BLUE}1/3${NC} LLM Provider"
    echo "  1) Mistral AI (recommended)"
    echo "  2) Anthropic Claude"
    echo "  3) OpenAI GPT"
    echo "  4) Ollama (local, free)"
    echo "  5) Google Gemini"
    echo "  6) Groq (fast, free tier)"
    echo "  7) DeepSeek"
    echo "  8) xAI Grok"
    read -rp "Choose [1]: " _provider_choice < /dev/tty
    case "${_provider_choice:-1}" in
        2)
            sed -i 's/^LLM_PROVIDER=.*/LLM_PROVIDER=anthropic/' "$INSTALL_DIR/.env"
            sed -i 's/^LLM_MODEL=.*/LLM_MODEL=claude-sonnet-4-20250514/' "$INSTALL_DIR/.env"
            echo -e -n "${BLUE}Anthropic API key: ${NC}"
            read -r _api_key < /dev/tty
            ;;
        3)
            sed -i 's/^LLM_PROVIDER=.*/LLM_PROVIDER=openai/' "$INSTALL_DIR/.env"
            sed -i 's/^LLM_MODEL=.*/LLM_MODEL=gpt-4o/' "$INSTALL_DIR/.env"
            echo -e -n "${BLUE}OpenAI API key: ${NC}"
            read -r _api_key < /dev/tty
            ;;
        4)
            sed -i 's/^LLM_PROVIDER=.*/LLM_PROVIDER=ollama/' "$INSTALL_DIR/.env"
            sed -i 's/^LLM_MODEL=.*/LLM_MODEL=llama3/' "$INSTALL_DIR/.env"
            sed -i 's/^# LLM_BASE_URL=.*/LLM_BASE_URL=http:\/\/localhost:11434\/v1/' "$INSTALL_DIR/.env"
            _api_key="ollama"
            ;;
        5)
            sed -i 's/^LLM_PROVIDER=.*/LLM_PROVIDER=gemini/' "$INSTALL_DIR/.env"
            sed -i 's/^LLM_MODEL=.*/LLM_MODEL=gemini-2.0-flash/' "$INSTALL_DIR/.env"
            echo -e -n "${BLUE}Google Gemini API key: ${NC}"
            read -r _api_key < /dev/tty
            ;;
        6)
            sed -i 's/^LLM_PROVIDER=.*/LLM_PROVIDER=groq/' "$INSTALL_DIR/.env"
            sed -i 's/^LLM_MODEL=.*/LLM_MODEL=llama-3.3-70b-versatile/' "$INSTALL_DIR/.env"
            echo -e -n "${BLUE}Groq API key: ${NC}"
            read -r _api_key < /dev/tty
            ;;
        7)
            sed -i 's/^LLM_PROVIDER=.*/LLM_PROVIDER=deepseek/' "$INSTALL_DIR/.env"
            sed -i 's/^LLM_MODEL=.*/LLM_MODEL=deepseek-chat/' "$INSTALL_DIR/.env"
            echo -e -n "${BLUE}DeepSeek API key: ${NC}"
            read -r _api_key < /dev/tty
            ;;
        8)
            sed -i 's/^LLM_PROVIDER=.*/LLM_PROVIDER=xai/' "$INSTALL_DIR/.env"
            sed -i 's/^LLM_MODEL=.*/LLM_MODEL=grok-3-mini/' "$INSTALL_DIR/.env"
            echo -e -n "${BLUE}xAI API key: ${NC}"
            read -r _api_key < /dev/tty
            ;;
        *)
            sed -i 's/^LLM_PROVIDER=.*/LLM_PROVIDER=mistral/' "$INSTALL_DIR/.env"
            sed -i 's/^LLM_MODEL=.*/LLM_MODEL=mistral-large-latest/' "$INSTALL_DIR/.env"
            echo -e -n "${BLUE}Mistral API key: ${NC}"
            read -r _api_key < /dev/tty
            ;;
    esac
    if [[ -n "$_api_key" ]]; then
        sed -i "s/^LLM_API_KEY=.*/LLM_API_KEY=${_api_key}/" "$INSTALL_DIR/.env"
    fi

    # Telegram
    echo ""
    echo -e "${BLUE}2/3${NC} Telegram Bot (get token from @BotFather)"
    echo -e -n "${BLUE}Telegram bot token (or Enter to skip): ${NC}"
    read -r _tg_token < /dev/tty
    if [[ -n "$_tg_token" ]]; then
        sed -i "s/^TELEGRAM_TOKEN=.*/TELEGRAM_TOKEN=${_tg_token}/" "$INSTALL_DIR/.env"
        # Enable telegram channel
        if grep -q "^ENABLED_CHANNELS=" "$INSTALL_DIR/.env"; then
            sed -i 's/^ENABLED_CHANNELS=.*/ENABLED_CHANNELS=["telegram"]/' "$INSTALL_DIR/.env"
        else
            echo 'ENABLED_CHANNELS=["telegram"]' >> "$INSTALL_DIR/.env"
        fi
    fi

    # Agent name
    echo ""
    echo -e "${BLUE}3/3${NC} Agent personality"
    echo -e -n "${BLUE}Agent name [Posipaka]: ${NC}"
    read -r _name < /dev/tty
    if [[ -n "$_name" ]]; then
        sed -i "s/^SOUL_NAME=.*/SOUL_NAME=${_name}/" "$INSTALL_DIR/.env"
    fi

    echo ""
    ok "Configuration saved to $INSTALL_DIR/.env"
fi

# ─── Deploy: Docker ─────────────────────────────────────────────────────────
deploy_docker() {
    log "Building and starting containers..."
    cd "$INSTALL_DIR/docker"

    $DOCKER compose down 2>/dev/null || true
    $DOCKER compose up -d --build

    log "Waiting for health check..."
    for i in $(seq 1 45); do
        if curl -sf http://localhost:8080/api/v1/health >/dev/null 2>&1; then
            ok "Health check passed after $((i*2))s"
            return 0
        fi
        sleep 2
    done
    err "Health check failed after 90s"
    echo "Check logs: $DOCKER logs posipaka"
    return 1
}

# ─── Deploy: Native Python ──────────────────────────────────────────────────
deploy_native() {
    log "Setting up Python environment..."

    # Find Python
    PYTHON=""
    for cmd in python3.12 python3.11 python3; do
        if command -v "$cmd" &>/dev/null; then
            ver=$($cmd -c 'import sys; print(sys.version_info >= (3,11))')
            if [[ "$ver" == "True" ]]; then
                PYTHON=$cmd; break
            fi
        fi
    done

    if [[ -z "$PYTHON" ]]; then
        err "Python 3.11+ not found. Install it first."
        exit 1
    fi
    log "Using $($PYTHON --version)"

    # Create venv
    cd "$INSTALL_DIR"
    $PYTHON -m venv .venv
    source .venv/bin/activate
    pip install --quiet --upgrade pip
    pip install --quiet -e ".[telegram]"

    # Create systemd service
    log "Creating systemd service..."
    sudo tee /etc/systemd/system/posipaka.service > /dev/null << UNIT
[Unit]
Description=Posipaka AI Agent
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/.venv/bin/posipaka start
Restart=on-failure
RestartSec=5
Environment=HOME=$HOME
EnvironmentFile=${INSTALL_DIR}/.env

[Install]
WantedBy=multi-user.target
UNIT

    sudo systemctl daemon-reload
    sudo systemctl enable posipaka
    sudo systemctl restart posipaka

    log "Waiting for health check..."
    for i in $(seq 1 30); do
        if curl -sf http://localhost:8080/api/v1/health >/dev/null 2>&1; then
            ok "Health check passed after $((i*2))s"
            return 0
        fi
        sleep 2
    done
    err "Health check failed. Check: sudo journalctl -u posipaka -f"
    return 1
}

# ─── Open firewall port if ufw is active ────────────────────────────────────
if command -v ufw &>/dev/null && sudo ufw status | grep -q "active"; then
    sudo ufw allow 8080/tcp >/dev/null 2>&1 && log "Firewall: opened port 8080"
fi

# ─── Run deploy ──────────────────────────────────────────────────────────────
case "$DEPLOY_METHOD" in
    docker) deploy_docker ;;
    native) deploy_native ;;
esac

# ─── Extract web password from logs ──────────────────────────────────────────
sleep 5  # дочекатись щоб контейнер встиг вивести пароль
_web_password=""
if [[ "$DEPLOY_METHOD" == "docker" ]]; then
    _web_password=$($DOCKER logs posipaka 2>&1 | grep -oP 'WEB UI PASSWORD: \K\S+' | head -1)
    # Fallback: спробувати прочитати з файлу і скинути
    if [[ -z "$_web_password" ]]; then
        _web_password=$($DOCKER exec posipaka posipaka reset-password 2>&1 | grep -oP 'NEW WEB UI PASSWORD: \K\S+' | head -1)
    fi
else
    _web_password=$(sudo journalctl -u posipaka --no-pager -n 50 2>&1 | grep -oP 'WEB UI PASSWORD: \K\S+' | head -1)
fi

# ─── Done ────────────────────────────────────────────────────────────────────
_ip=$(hostname -I | awk '{print $1}')
echo ""
echo -e "${GREEN}${BOLD}Posipaka deployed successfully!${NC}"
echo ""
echo "  Web UI:  http://${_ip}:8080"
if [[ -n "$_web_password" ]]; then
    echo -e "  Password: ${YELLOW}${BOLD}${_web_password}${NC}  (save it, shown only once!)"
fi
echo ""
if [[ "$DEPLOY_METHOD" == "docker" ]]; then
    echo "  Logs:    $DOCKER logs posipaka -f"
else
    echo "  Logs:    sudo journalctl -u posipaka -f"
fi
echo "  Config:  $INSTALL_DIR/.env"
echo ""
echo "Next: send a message to your Telegram bot!"
