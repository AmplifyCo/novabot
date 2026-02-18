#!/bin/bash
# Install Digital Twin setup command globally
# This creates a symlink in /usr/local/bin for easy access

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_SCRIPT="$SCRIPT_DIR/setup"
INSTALL_DIR="/usr/local/bin"
COMMAND_NAME="dt-setup"

echo "📦 Installing Digital Twin setup command..."

# Check if setup script exists
if [ ! -f "$SETUP_SCRIPT" ]; then
    echo "❌ Error: setup script not found at $SETUP_SCRIPT"
    exit 1
fi

# Make setup script executable
chmod +x "$SETUP_SCRIPT"

# Check if /usr/local/bin exists and is writable
if [ ! -d "$INSTALL_DIR" ]; then
    echo "⚠️  $INSTALL_DIR does not exist. Creating it..."
    sudo mkdir -p "$INSTALL_DIR"
fi

# Create symlink
echo "🔗 Creating symlink: $INSTALL_DIR/$COMMAND_NAME -> $SETUP_SCRIPT"

if [ -L "$INSTALL_DIR/$COMMAND_NAME" ] || [ -f "$INSTALL_DIR/$COMMAND_NAME" ]; then
    echo "⚠️  $INSTALL_DIR/$COMMAND_NAME already exists. Removing old version..."
    sudo rm -f "$INSTALL_DIR/$COMMAND_NAME"
fi

sudo ln -s "$SETUP_SCRIPT" "$INSTALL_DIR/$COMMAND_NAME"

echo "✅ Installation complete!"
echo ""
echo "You can now run the setup wizard from anywhere using:"
echo "  dt-setup              # Full wizard"
echo "  dt-setup digital-twin # Full setup"
echo "  dt-setup email        # Configure email only"
echo "  dt-setup telegram     # Configure Telegram only"
echo "  dt-setup core         # Configure API keys only"
echo ""
echo "Or from the project directory:"
echo "  ./setup               # Local command"
echo ""
