#!/usr/bin/env bash
set -euo pipefail

# ─── Кольори ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'; BOLD='\033[1m'

# ─── Banner ───────────────────────────────────────────────────────────────────
echo -e "${BLUE}${BOLD}"
cat << 'EOF'
██████╗  ██████╗ ███████╗██╗██████╗  █████╗ ██╗  ██╗ █████╗
██╔══██╗██╔═══██╗██╔════╝██║██╔══██╗██╔══██╗██║ ██╔╝██╔══██╗
██████╔╝██║   ██║███████╗██║██████╔╝███████║█████╔╝ ███████║
██╔═══╝ ██║   ██║╚════██║██║██╔═══╝ ██╔══██║██╔═██╗ ██╔══██║
██║     ╚██████╔╝███████║██║██║     ██║  ██║██║  ██╗██║  ██║
╚═╝      ╚═════╝ ╚══════╝╚═╝╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝
EOF
echo -e "${NC}"
echo -e "Ваш персональний AI-агент. Встановлення..."
echo ""

# ─── Визначення OS ────────────────────────────────────────────────────────────
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if command -v apt-get &> /dev/null; then OS="debian"
        elif command -v dnf &> /dev/null; then OS="fedora"
        elif command -v pacman &> /dev/null; then OS="arch"
        else OS="linux"
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then OS="macos"
    else
        echo -e "${RED}Непідтримувана ОС: $OSTYPE${NC}"
        exit 1
    fi
}

# ─── Python check ────────────────────────────────────────────────────────────
check_or_install_python() {
    PYTHON=""
    for cmd in python3.12 python3.11 python3; do
        if command -v $cmd &> /dev/null; then
            ver=$($cmd -c 'import sys; print(sys.version_info >= (3,11))')
            if [[ "$ver" == "True" ]]; then
                PYTHON=$cmd; break
            fi
        fi
    done

    if [[ -z "$PYTHON" ]]; then
        echo -e "${YELLOW}Python 3.11+ не знайдено. Встановлюємо...${NC}"
        case $OS in
            debian) sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv python3-pip ;;
            fedora) sudo dnf install -y python3.12 ;;
            arch) sudo pacman -S --noconfirm python ;;
            macos) brew install python@3.12 ;;
            *) echo -e "${RED}Встановіть Python 3.11+ вручну${NC}"; exit 1 ;;
        esac
        PYTHON=python3.12
    fi
    echo -e "${GREEN}Python: $($PYTHON --version)${NC}"
}

# ─── pip install ─────────────────────────────────────────────────────────────
install_posipaka() {
    echo -e "${BLUE}Встановлення Posipaka...${NC}"
    $PYTHON -m pip install --quiet --upgrade pip
    $PYTHON -m pip install --quiet posipaka
    echo -e "${GREEN}Posipaka встановлено${NC}"
}

# ─── Playwright ──────────────────────────────────────────────────────────────
install_playwright() {
    echo -e "${BLUE}Встановлення браузера (Playwright)...${NC}"
    $PYTHON -m playwright install chromium --with-deps 2>/dev/null || true
    echo -e "${GREEN}Браузер готовий${NC}"
}

# ─── Run wizard ──────────────────────────────────────────────────────────────
run_setup() {
    echo ""
    echo -e "${GREEN}${BOLD}Встановлення завершено!${NC}"
    echo ""
    echo -e "Запускаємо майстер налаштування..."
    sleep 1
    $PYTHON -m posipaka setup
}

# ─── Main ─────────────────────────────────────────────────────────────────────
detect_os
check_or_install_python
install_posipaka
install_playwright
run_setup
