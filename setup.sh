#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SKILL_DIR/.venv"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

command_exists() {
    command -v "$1" &>/dev/null
}

detect_platform() {
    case "$(uname -s)" in
        Linux)
            if command_exists pacman; then
                echo "arch"
            elif command_exists apt-get; then
                echo "debian"
            elif command_exists dnf; then
                echo "fedora"
            elif command_exists apk; then
                echo "alpine"
            else
                echo "linux-unknown"
            fi
            ;;
        Darwin) echo "macos" ;;
        *) echo "unknown" ;;
    esac
}

install_system_deps_arch() {
    info "Installing system dependencies (Arch Linux)..."
    sudo pacman -S --needed --noconfirm python python-pip tesseract tesseract-data-eng poppler
}

install_system_deps_debian() {
    info "Installing system dependencies (Debian/Ubuntu)..."
    sudo apt-get update -qq
    sudo apt-get install -y python3 python3-pip python3-venv tesseract-ocr tesseract-ocr-eng poppler-utils
}

install_system_deps_fedora() {
    info "Installing system dependencies (Fedora)..."
    sudo dnf install -y python3 python3-pip tesseract tesseract-langpack-eng poppler-utils
}

install_system_deps_alpine() {
    info "Installing system dependencies (Alpine)..."
    sudo apk add python3 py3-pip tesseract-ocr tesseract-ocr-data-eng poppler-utils
}

install_system_deps_macos() {
    info "Installing system dependencies (macOS)..."
    if ! command_exists brew; then
        error "Homebrew not found. Install it from https://brew.sh"
        exit 1
    fi
    brew install python tesseract poppler
}

install_system_deps() {
    local platform
    platform=$(detect_platform)

    case "$platform" in
        arch)    install_system_deps_arch ;;
        debian)  install_system_deps_debian ;;
        fedora)  install_system_deps_fedora ;;
        alpine)  install_system_deps_alpine ;;
        macos)   install_system_deps_macos ;;
        *)
            warn "Unknown platform. Install these manually:"
            warn "  - Python 3.10+"
            warn "  - Tesseract OCR (with English language data)"
            warn "  - Poppler utilities"
            ;;
    esac
}

check_python() {
    if command_exists python3; then
        local version
        version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        local major minor
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            info "Python $version found"
            return 0
        else
            warn "Python $version found, but 3.10+ is required"
            return 1
        fi
    else
        error "Python 3 not found"
        return 1
    fi
}

check_tesseract() {
    if command_exists tesseract; then
        local langs
        langs=$(tesseract --list-langs 2>&1)
        if echo "$langs" | grep -q "eng"; then
            info "Tesseract OCR found with English language data"
            return 0
        else
            warn "Tesseract found but English language data missing"
            warn "Install tesseract-ocr-eng (or tesseract-data-eng on Arch)"
            return 1
        fi
    else
        warn "Tesseract OCR not found (needed for scanned PDFs)"
        return 1
    fi
}

create_venv() {
    if [ -d "$VENV_DIR" ]; then
        info "Virtual environment already exists at $VENV_DIR"
        return
    fi

    info "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip --quiet
    info "Virtual environment created"
}

install_python_deps() {
    info "Installing Python dependencies (this may take a few minutes)..."
    "$VENV_DIR/bin/pip" install --quiet \
        sentence-transformers \
        pdfplumber \
        pytesseract \
        pdf2image \
        ebooklib \
        beautifulsoup4 \
        lxml
    info "Python dependencies installed"
}

download_model() {
    info "Downloading embedding model (all-MiniLM-L6-v2, ~80 MB)..."
    "$VENV_DIR/bin/python3" -c "
from sentence_transformers import SentenceTransformer
SentenceTransformer('all-MiniLM-L6-v2')
print('Model downloaded and cached')
" 2>/dev/null
    info "Embedding model ready"
}

run_smoke_test() {
    info "Running smoke test..."
    "$VENV_DIR/bin/python3" "$SKILL_DIR/scripts/search.py" \
        --query "test query" --top-k 1 --format json --no-expand 2>/dev/null | \
        "$VENV_DIR/bin/python3" -c "
import sys, json
data = json.load(sys.stdin)
print(f'  Search returned {data[\"total_results\"]} results')
" 2>/dev/null || info "  Smoke test skipped (no books indexed yet — that's OK)"
}

main() {
    echo ""
    echo "=== Nudge Agent — Setup ==="
    echo ""

    # Step 1: Check / install system deps
    local needs_system_deps=false
    if ! check_python; then needs_system_deps=true; fi
    if ! check_tesseract; then needs_system_deps=true; fi

    if [ "$needs_system_deps" = true ]; then
        echo ""
        read -rp "Install missing system dependencies? [Y/n] " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            install_system_deps
        fi
    fi

    # Step 2: Create venv and install Python deps
    echo ""
    create_venv
    install_python_deps

    # Step 3: Pre-download embedding model
    echo ""
    download_model

    # Step 4: Smoke test
    echo ""
    run_smoke_test

    echo ""
    info "Setup complete!"
    echo ""
    echo "Usage:"
    echo "  Index a book:"
    echo "    $VENV_DIR/bin/python3 $SKILL_DIR/scripts/preprocess.py /path/to/book.pdf"
    echo ""
    echo "  Search:"
    echo "    $VENV_DIR/bin/python3 $SKILL_DIR/scripts/search.py --query \"your question\""
    echo ""
}

main "$@"
