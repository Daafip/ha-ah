#!/usr/bin/env bash
# Removes the appie:// handler installed by install-appie-catcher.sh.
# The output file (default ~/appie-code.txt) is left alone.

set -euo pipefail

BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"

rm -f "$BIN_DIR/appie-catcher.sh" "$APPS_DIR/appie-catcher.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR"
fi

echo "Removed. appie:// links will fail to open again (the documented copy-paste"
echo "fallback in the login dialog still works)."
