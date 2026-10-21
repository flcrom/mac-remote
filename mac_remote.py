#!/usr/bin/env python3
# Mac receiver v3 for the phone gesture remote (dev.flcrom.remote) - player-agnostic.
# v3: advertises _mremote._tcp via dns-sd (same-WiFi auto-discovery, no Tailscale
# needed at home) and reports what is playing back to the phone ("T <title>" lines).
# Listens on 0.0.0.0:47842 for one-letter commands and routes them to whatever
# is currently playing: Music, Spotify, or a browser tab (YouTube / Netflix / other).
#
#   P = play/pause   F = +10s   B = -10s   + = faster   - = slower
#
# Routing priority (first match wins): Music playing > Spotify playing >
# browser active tab (YouTube / Netflix / generic) > frontmost browser keys.
# The route is cached for 2 s so gesture bursts stay fast.
#
# Honest capability table:
#   gesture     YouTube      Netflix       Music/Spotify      QuickTime
#   tap         k            space         playpause          play/pause
#   +-10s       j / l        arrow keys    player position    current time
#   speed       shift+. / ,  NOT POSSIBLE  NOT POSSIBLE       rate
# Unsupported commands are no-ops and get printed here (the phone cannot know).
#
# Needs: python3 (built into macOS) + Accessibility permission for Terminal
# (System Settings -> Privacy & Security -> Accessibility -> Terminal on).
#
# Env:  REMOTE_PORT  listen port (default 47842)
import os, socket, subprocess, time, threading, atexit

PORT = int(os.environ.get("REMOTE_PORT", "47842"))
ROUTE_TTL = 2.0

DETECT = r'''
tell application "System Events" to set procs to name of processes
if procs contains "Music" then
	try
		tell application "Music" to if player state is playing then return "music"
	end try
end if
if procs contains "Spotify" then
	try
		tell application "Spotify" to if player state is playing then return "spotify"
	end try
end if
if procs contains "QuickTime Player" then
	try
		tell application "QuickTime Player" to if (count of documents) > 0 then
			if playing of document 1 then return "quicktime"
		end if
	end try
end if
if procs contains "Google Chrome" then
	try
		tell application "Google Chrome" to set u to URL of active tab of front window
		if u contains "youtube.com" then return "youtube"
		if u contains "netflix.com" then return "netflix"
		return "chrome"
	end try
end if
if procs contains "Safari" then
	try
		tell application "Safari" to set u to URL of front document
		if u contains "youtube.com" then return "youtube-safari"
		if u contains "netflix.com" then return "netflix-safari"
		return "safari"
	end try
end if
return "none"
'''

def keys(proc, body):
    return 'tell application "System Events" to tell (first process whose name is "%s") to %s' % (proc, body)

# per-route applescript per command; value = (applescript, browser_proc or None)
def build_cmds(route):
    br = None
    if route in ("youtube", "netflix", "chrome"): br = "Google Chrome"
    if route in ("youtube-safari", "netflix-safari", "safari"): br = "Safari"
    yt = route.startswith("youtube"); nf = route.startswith("netflix")
    c = {}
    if route == "music":
        c['P'] = 'tell application "Music" to playpause'
        c['F'] = 'tell application "Music" to set player position to ((player position) + 10)'
        c['B'] = 'tell application "Music" to set player position to ((player position) - 10)'
    elif route == "spotify":
        c['P'] = 'tell application "Spotify" to playpause'
        c['F'] = 'tell application "Spotify" to set player position to ((player position) + 10)'
        c['B'] = 'tell application "Spotify" to set player position to ((player position) - 10)'
    elif route == "quicktime":
        c['P'] = 'tell application "QuickTime Player" to tell document 1 to if playing then pause else play'
        c['F'] = 'tell application "QuickTime Player" to set current time of document 1 to ((current time of document 1) + 10)'
        c['B'] = 'tell application "QuickTime Player" to set current time of document 1 to ((current time of document 1) - 10)'
        c['+'] = 'tell application "QuickTime Player" to set rate of document 1 to ((rate of document 1) + 0.25)'
        c['-'] = 'tell application "QuickTime Player" to set rate of document 1 to ((rate of document 1) - 0.25)'
    elif yt and br:
        c['P'] = keys(br, 'keystroke "k"')
        c['F'] = keys(br, 'keystroke "l"')
        c['B'] = keys(br, 'keystroke "j"')
        c['+'] = keys(br, 'key code 47 using {shift down}')
        c['-'] = keys(br, 'key code 43 using {shift down}')
    elif nf and br:
        c['P'] = keys(br, 'key code 49')            # space
        c['F'] = keys(br, 'key code 124')           # right arrow
        c['B'] = keys(br, 'key code 123')           # left arrow
    elif br:
        c['P'] = keys(br, 'key code 49')
        c['F'] = keys(br, 'key code 124')
        c['B'] = keys(br, 'key code 123')
    return c


TITLE = r'''
tell application "System Events" to set procs to name of processes
if procs contains "Music" then
	try
		tell application "Music" to if player state is playing then
			return "Music: " & (name of current track) & " - " & (artist of current track)
		end if
	end try
end if
if procs contains "Spotify" then
	try
		tell application "Spotify" to if player state is playing then
			return "Spotify: " & (name of current track) & " - " & (artist of current track)
		end if
	end try
end if
if procs contains "QuickTime Player" then
	try
		tell application "QuickTime Player" to if (count of documents) > 0 then
			return "QuickTime: " & (name of document 1)
		end if
	end try
end if
if procs contains "Google Chrome" then
	try
		tell application "Google Chrome" to set t to title of active tab of front window
		if t is not "" then return "Chrome: " & t
	end try
end if
if procs contains "Safari" then
	try
		tell application "Safari" to set t to name of front document
		if t is not "" then return "Safari: " & t
	end try
end if
return ""
'''

_clients = []
_clients_lock = threading.Lock()

def _bcast(line):
    data = (line + "\n").encode()
    with _clients_lock:
        dead = []
        for c in _clients:
            try:
                c.sendall(data)
            except Exception:
                dead.append(c)
        for c in dead:
            _clients.remove(c)

def title_loop():
    last = None
    while True:
        try:
            out = subprocess.run(['osascript', '-e', TITLE], capture_output=True, timeout=4)
            t = ' '.join(out.stdout.decode(errors='replace').split())[:90]
            if t and t != last:
                last = t
                _bcast('T ' + t)
        except Exception:
            pass
        time.sleep(3)

def advertise():
    # built-in macOS command; broadcasts "flcrommac._mremote._tcp.local" on the LAN
    try:
        p = subprocess.Popen(['dns-sd', '-R', 'flcrommac', '_mremote._tcp', 'local', str(PORT)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        atexit.register(p.terminate)
        print('advertising flcrommac._mremote._tcp on the local network (dns-sd)', flush=True)
    except Exception as e:
        print('dns-sd advertise failed (Tailscale fallback still works): %s' % e, flush=True)

_route = ("none", 0.0)
def current_route():
    global _route
    r, at = _route
    if time.time() - at < ROUTE_TTL:
        return r
    try:
        out = subprocess.run(['osascript', '-e', DETECT], capture_output=True, timeout=4)
        r = out.stdout.decode().strip() or "none"
    except Exception:
        r = "none"
    _route = (r, time.time())
    return r

def run(cmd):
    t0 = time.time()
    route = current_route()
    cmds = build_cmds(route)
    if cmd not in cmds:
        print('%s -> %s: NOT SUPPORTED in this app (no-op)' % (cmd, route), flush=True)
        return
    try:
        r = subprocess.run(['osascript', '-e', cmds[cmd]], capture_output=True, timeout=3)
        ms = (time.time() - t0) * 1000
        if r.returncode != 0:
            err = r.stderr.decode(errors='replace').strip()
            print('%s -> %s FAILED (%.0f ms): %s' % (cmd, route, ms, err[:160]), flush=True)
            if 'assistive' in err.lower() or 'not allowed' in err.lower():
                print('>> grant Accessibility to Terminal: System Settings -> Privacy & Security -> Accessibility', flush=True)
        else:
            print('%s -> %s ok (%.0f ms)' % (cmd, route, ms), flush=True)
    except Exception as e:
        print('%s -> %s error: %s' % (cmd, route, e), flush=True)

def handle(conn, addr):
    print('phone connected from %s' % (addr,), flush=True)
    with _clients_lock:
        _clients.append(conn)
    buf = b''
    try:
        while True:
            data = conn.recv(64)
            if not data:
                break
            buf += data
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                c = line.strip().decode(errors='replace')
                if c in ('P', 'F', 'B', '+', '-'):
                    run(c)
    finally:
        with _clients_lock:
            if conn in _clients: _clients.remove(conn)
        conn.close()
        print('phone disconnected', flush=True)

def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', PORT))
    srv.listen(1)
    print('mac remote receiver v3 on port %d - routes to whatever is playing' % PORT, flush=True)
    print('(Music / Spotify / QuickTime / YouTube / Netflix; speed is impossible in Netflix, Music and Spotify)', flush=True)
    advertise()
    threading.Thread(target=title_loop, daemon=True).start()
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=handle, args=(conn, addr), daemon=True).start()

if __name__ == '__main__':
    main()
