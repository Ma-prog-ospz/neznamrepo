import requests
from flask import Flask, Response, jsonify
import threading
import time

PORTAL = "http://mag.trexlive.me/"
MAC = "00:1A:79:BB:8D:EA"

app = Flask(__name__)
session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 (QtEmbedded; Linux) MAG254 stbapp ver: 2 rev: 2",
    "X-User-Agent": "Model: MAG254; Link: WiFi",
    "Referer": PORTAL,
    "Connection": "keep-alive",
    "Accept": "*/*"
})
session.cookies.update({"mac": MAC})

token = None
channels = []
profile = {}

# -----------------------------
# HANDSHAKE
# -----------------------------
def do_handshake():
    global token
    r = session.get(f"{PORTAL}portal.php?action=handshake&type=stb&token=&JsHttpRequest=1-xml", timeout=10)
    try:
        token = r.json()["js"]["token"]
        session.headers.update({"Authorization": f"Bearer {token}"})
        print("Handshake OK:", token)
    except:
        print("Handshake FAILED:", r.text)

# -----------------------------
# PROFILE
# -----------------------------
def load_profile():
    global profile
    r = session.get(f"{PORTAL}portal.php?type=account_info&action=get_main_info&JsHttpRequest=1-xml", timeout=10)
    try:
        profile = r.json().get("js", {})
        print("Profile OK")
    except:
        print("Profile FAILED:", r.text)
        profile = {}

# -----------------------------
# CHANNEL LIST
# -----------------------------
def load_channels():
    global channels
    r = session.get(f"{PORTAL}portal.php?type=itv&action=get_all_channels&JsHttpRequest=1-xml", timeout=15)
    try:
        channels = r.json()["js"]["data"]
        print("Channels loaded:", len(channels))
    except:
        print("Channel list FAILED:", r.text)
        channels = []

# -----------------------------
# TOKEN REFRESH
# -----------------------------
def token_refresh():
    global token
    while True:
        try:
            r = session.get(f"{PORTAL}portal.php?action=handshake&type=stb&token=&JsHttpRequest=1-xml", timeout=10).json()
            token = r["js"]["token"]
            session.headers.update({"Authorization": f"Bearer {token}"})
            print("Token refreshed:", token)
        except:
            print("Token refresh FAILED")
        time.sleep(25)

# -----------------------------
# ⭐ STABILNI MAG EMULATOR KEEPALIVE (svakih 5s)
# -----------------------------
def mag_emulator_keepalive(stream_id):
    while True:
        try:
            # 1) MAG ping
            session.get(f"{PORTAL}server/load.php?type=stb&action=ping", timeout=5)

            # 2) MAG events
            session.get(f"{PORTAL}server/load.php?type=stb&action=get_events", timeout=5)

            # 3) MAG profile check
            session.get(f"{PORTAL}server/load.php?type=stb&action=get_profile", timeout=5)

            # 4) MAG stream status
            session.get(
                f"{PORTAL}server/load.php?type=itv&action=get_stream_status&cmd={stream_id}",
                timeout=5
            )

            print(f"MAG KEEPALIVE OK → {stream_id}")

        except Exception as e:
            print(f"MAG KEEPALIVE FAILED → {stream_id}", e)

        time.sleep(5)  # MAG radi 3–7s

# -----------------------------
# STREAM URL
# -----------------------------
def create_stream(stream_id):
    return f"{PORTAL}play/live.php?mac={MAC}&stream={stream_id}&extension=ts"

# -----------------------------
# STREAM (HOT RELOAD – NE PREKIDA, MINIMALNO VRAĆANJE)
# -----------------------------
@app.route("/live/ftv/ftv/<stream_id>.ts")
def xtream_stream(stream_id):
    real_url = create_stream(stream_id)
    print("Streaming:", real_url)

    threading.Thread(target=mag_emulator_keepalive, args=(stream_id,), daemon=True).start()

    def open_stream():
        return session.get(
            real_url,
            stream=True,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0 (QtEmbedded; Linux) MAG254 stbapp ver: 2 rev: 2",
                "X-User-Agent": "Model: MAG254; Link: WiFi",
                "Connection": "keep-alive",
                "Accept": "*/*",
                "Referer": PORTAL
            }
        )

    def generate():
        current = open_stream()
        backup = None
        backup_ready = False

        for chunk in current.iter_content(chunk_size=4096):
            if chunk:
                yield chunk

            # ako backup nije pokrenut → pokreni ga u pozadini
            if backup is None:
                try:
                    backup = open_stream()
                except:
                    backup = None

            # ako backup počne slati podatke → prebacujemo se
            if backup and not backup_ready:
                try:
                    test = next(backup.iter_content(chunk_size=4096))
                    backup_ready = True
                    current = backup
                    backup = None
                except StopIteration:
                    backup = None
                except:
                    backup = None

        # ako current pukne → hot reload
        while True:
            try:
                current = open_stream()
                for chunk in current.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
            except:
                time.sleep(0.05)
                continue

    return Response(generate(), content_type="video/mp2t")

# -----------------------------
# M3U
# -----------------------------
@app.route("/playlist.m3u")
def playlist():
    out = "#EXTM3U\n"
    for ch in channels:
        out += f'#EXTINF:-1 tvg-logo="{ch.get("logo","")}",{ch.get("name","Unknown")}\n'
        out += f"http://localhost:8000/live/ftv/ftv/{ch.get('id')}.ts\n"
    return Response(out, mimetype="application/x-mpegURL")

# -----------------------------
# STARTUP
# -----------------------------
def startup():
    do_handshake()
    load_profile()
    load_channels()

    threading.Thread(target=token_refresh, daemon=True).start()

if __name__ == "__main__":
    startup()
    app.run(host="0.0.0.0", port=8000)
