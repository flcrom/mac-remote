# mac-remote

Phone-gesture media remote for macOS. The Android app (dev.flcrom.remote) sends
one-letter commands over TCP; `mac_remote.py` on the Mac routes them to whatever
is playing (Music / Spotify / QuickTime / YouTube / Netflix in Chrome or Safari).

The Mac side runs under a per-user launchd agent (`run.sh` + the plist) that
starts the receiver at login, restarts it on crash, and self-updates it from
this repo every 5 minutes - a new `mac_remote.py` is installed only when its
sha256 matches `SHA256SUMS`.

## Setup (one time)

    mkdir -p ~/macremote ~/Library/LaunchAgents
    cd ~/macremote
    curl -fsSL https://raw.githubusercontent.com/flcrom/mac-remote/main/run.sh -o run.sh
    curl -fsSL https://raw.githubusercontent.com/flcrom/mac-remote/main/dev.flcrom.macremote.plist -o ~/Library/LaunchAgents/dev.flcrom.macremote.plist
    chmod +x run.sh
    launchctl load -w ~/Library/LaunchAgents/dev.flcrom.macremote.plist

## Updating the receiver

Push a new `mac_remote.py` and a regenerated `SHA256SUMS`; every Mac running the
agent picks it up within ~10 minutes and restarts the receiver.

Commands: `P` play/pause, `F` +10s, `B` -10s, `+`/`-` speed 0.25x steps
(speed is not possible in Netflix, Music or Spotify - logged as a no-op).
The receiver advertises `_mremote._tcp` via dns-sd for same-WiFi discovery and
reports what is playing back to the phone (`T <title>` lines).
