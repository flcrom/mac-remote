#!/bin/bash
# Mac Remote agent: keeps the receiver running and self-updates it from GitHub.
# Started at login by ~/Library/LaunchAgents/dev.flcrom.macremote.plist.
# Trust model: code is fetched only from flcrom's own repo over HTTPS, and a
# new receiver is installed only if its sha256 matches the repo's SHA256SUMS.
BASE="https://raw.githubusercontent.com/flcrom/mac-remote/main"
DIR="$HOME/Library/Application Support/macremote"
mkdir -p "$DIR"; cd "$DIR" || exit 1
while true; do
  remote_sum=$(curl -fsSL --max-time 10 "$BASE/SHA256SUMS" 2>/dev/null | awk '{print $1}')
  local_sum=$(shasum -a 256 "$DIR/mac_remote.py" 2>/dev/null | awk '{print $1}')
  if [ -n "$remote_sum" ] && [ "$remote_sum" != "$local_sum" ]; then
    if curl -fsSL --max-time 20 "$BASE/mac_remote.py" -o "$DIR/mac_remote.py.new" 2>/dev/null; then
      new_sum=$(shasum -a 256 "$DIR/mac_remote.py.new" | awk '{print $1}')
      if [ "$new_sum" = "$remote_sum" ]; then
        mv "$DIR/mac_remote.py.new" "$DIR/mac_remote.py"
        pkill -f "python3 $DIR/mac_remote.py"
        echo "$(date): receiver updated (sha256 ${remote_sum:0:12}...)" >> "$DIR/agent.log"
      else
        rm -f "$DIR/mac_remote.py.new"
        echo "$(date): checksum mismatch, update refused" >> "$DIR/agent.log"
      fi
    fi
  fi
  if ! pgrep -f "python3 $DIR/mac_remote.py" >/dev/null 2>&1; then
    python3 "$DIR/mac_remote.py" >> "$DIR/receiver.log" 2>&1 &
  fi
  sleep 300
done
