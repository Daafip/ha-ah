#!/usr/bin/env bash
# Registers a handler for appie:// links on a freedesktop-compliant Linux
# desktop (GNOME, KDE, XFCE, ...), so the AH login redirect
# (appie://login-exit?code=...) gets caught instead of failing silently.
#
# The code is appended to a file you tail after logging in — nothing is
# executed automatically beyond writing that line.
#
# Usage: scripts/install-appie-catcher.sh [output-file]
#   output-file defaults to ~/appie-code.txt
#
# Requires: xdg-utils (xdg-mime, update-desktop-database) — present by
# default on most desktop Linux distros.

set -euo pipefail

OUTPUT_FILE="${1:-$HOME/appie-code.txt}"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
CATCHER="$BIN_DIR/appie-catcher.sh"
DESKTOP_FILE="$APPS_DIR/appie-catcher.desktop"

for cmd in xdg-mime update-desktop-database; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "error: $cmd not found — this script needs a freedesktop-compliant Linux desktop." >&2
    exit 1
  fi
done

mkdir -p "$BIN_DIR" "$APPS_DIR"

cat >"$CATCHER" <<SCRIPT
#!/usr/bin/env bash
# Installed by install-appie-catcher.sh; re-run that script to change the output file.
echo "\$1" >>"$OUTPUT_FILE"
if command -v notify-send >/dev/null 2>&1; then
  notify-send "Albert Heijn login" "Code captured — see $OUTPUT_FILE"
fi
SCRIPT
chmod +x "$CATCHER"

cat >"$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Appie Code Catcher
Exec=$CATCHER %u
MimeType=x-scheme-handler/appie;
NoDisplay=true
DESKTOP

update-desktop-database "$APPS_DIR"
xdg-mime default "$(basename "$DESKTOP_FILE")" x-scheme-handler/appie

echo "Installed. appie:// links now append the code to: $OUTPUT_FILE"
echo "After logging in via the AH authorize URL, run:  tail -1 $OUTPUT_FILE"
echo "To remove it again: scripts/uninstall-appie-catcher.sh"
