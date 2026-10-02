#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
LABEL="com.codex.noc-monitoring"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_DIR="$ROOT_DIR/outputs/pleno_business_monitor/logs"

mkdir -p "$PLIST_DIR" "$LOG_DIR"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>cd "$ROOT_DIR" &amp;&amp; { printf "__file__ = \"%s\"\n" "$ROOT_DIR/scripts/noc_monitor_dispatcher.py"; cat "$ROOT_DIR/scripts/noc_monitor_dispatcher.py"; } | /usr/bin/python3</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT_DIR</string>
  <key>StartInterval</key>
  <integer>60</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/launchd_noc_monitoring.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/launchd_noc_monitoring.err.log</string>
</dict>
</plist>
EOF

UID_VALUE="$(id -u)"
DOMAIN="gui/$UID_VALUE"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
launchctl kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1 || true

echo "LaunchAgent instalado: $PLIST_PATH"
echo "Label: $LABEL"
