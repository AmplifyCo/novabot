#!/bin/bash
# Nova Voice Client — Raspberry Pi / Linux setup script
#
# Usage:
#   curl -sL https://raw.githubusercontent.com/AmplifyCo/novabot/main/clients/setup.sh | bash
#
# Or manually:
#   chmod +x setup.sh && ./setup.sh

set -e

INSTALL_DIR="$HOME/nova-voice"
REPO_BASE="https://raw.githubusercontent.com/AmplifyCo/novabot/main/clients"

echo "==========================================="
echo "  Nova Voice Client — Setup"
echo "==========================================="
echo ""

# ── System packages ──────────────────────────────────────────────────────

echo "[1/5] Installing system packages..."
if command -v apt-get &>/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-pip python3-venv portaudio19-dev mpv espeak-ng
elif command -v dnf &>/dev/null; then
    sudo dnf install -y python3 python3-pip portaudio-devel mpv espeak-ng
elif command -v brew &>/dev/null; then
    brew install portaudio mpv espeak
else
    echo "  Unknown package manager — install manually: portaudio, mpv, espeak-ng"
fi

# ── Create install directory ─────────────────────────────────────────────

echo "[2/5] Setting up $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# ── Download files ───────────────────────────────────────────────────────

echo "[3/5] Downloading Nova Voice Client..."
curl -sL "$REPO_BASE/nova_voice.py" -o nova_voice.py
curl -sL "$REPO_BASE/requirements-voice.txt" -o requirements.txt

# ── Python venv + dependencies ───────────────────────────────────────────

echo "[4/5] Installing Python dependencies..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Raspberry Pi GPIO (optional, won't fail on non-Pi)
pip install RPi.GPIO -q 2>/dev/null || true

echo "[5/5] Done!"

# ── Create .env if it doesn't exist ─────────────────────────────────────

if [ ! -f .env ]; then
    cat > .env << 'ENVEOF'
# Nova Voice Client Configuration
NOVA_URL=https://webhook.amplify-pixels.com
NOVA_API_KEY=

# Audio devices (leave empty for auto-detect)
# Run: python -m sounddevice   to list devices
AUDIO_DEVICE_IN=
AUDIO_DEVICE_OUT=

# Conversation tuning
SESSION_TIMEOUT=30
SILENCE_THRESHOLD=500

# Raspberry Pi GPIO LED pin (0 = disabled)
LED_PIN=0
ENVEOF
    echo ""
    echo "==========================================="
    echo "  IMPORTANT: Edit your API key"
    echo "==========================================="
    echo ""
    echo "  nano $INSTALL_DIR/.env"
    echo ""
    echo "  Set NOVA_API_KEY to your Nova API key."
    echo ""
fi

echo "==========================================="
echo "  To run:"
echo "==========================================="
echo ""
echo "  cd $INSTALL_DIR"
echo "  source venv/bin/activate"
echo "  python nova_voice.py"
echo ""
echo "  Or as a service:"
echo "  sudo cp nova-voice.service /etc/systemd/system/"
echo "  sudo systemctl enable --now nova-voice"
echo ""

# ── Create systemd service file ──────────────────────────────────────────

cat > nova-voice.service << SVCEOF
[Unit]
Description=Nova Voice Client — Hey Nova
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/nova_voice.py
Restart=on-failure
RestartSec=5
EnvironmentFile=$INSTALL_DIR/.env

[Install]
WantedBy=multi-user.target
SVCEOF

echo "Setup complete!"
