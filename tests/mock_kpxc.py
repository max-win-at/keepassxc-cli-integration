#!/usr/bin/env python3
"""Mock KeePassXC BrowserServer for offline end-to-end testing of kpxc-agent.

Implements the server half of the protocol faithfully enough to exercise the real
code paths: the bare-JSON transport the local BrowserServer socket speaks (no
length framing - a proxy adds that), the crypto_box handshake, per-connection
association (get-logins refuses until test-associate has run on the connection),
and the empty-ack frame that precedes a generate-password reply. Listens on an
AF_UNIX socket (argv[1]).

With ``--proxy-stdio SOCKET`` it instead acts as a stand-in for keepassxc-proxy:
it reads native-messaging framing on stdin, relays to the bare-JSON socket, and
frames the replies back on stdout. This exercises the ExecTransport relay path
(e.g. keepassxc-proxy.exe across WSL) offline.
"""
import base64, ctypes, ctypes.util, json, os, socket, struct, sys, threading, time

NONCE, MAC = 24, 16
S = ctypes.CDLL(ctypes.util.find_library("sodium") or "libsodium.so.26"); S.sodium_init()


def keypair():
    pk, sk = ctypes.create_string_buffer(32), ctypes.create_string_buffer(32)
    S.crypto_box_keypair(pk, sk); return pk.raw, sk.raw


def box(m, n, pk, sk):
    c = ctypes.create_string_buffer(len(m) + MAC)
    assert S.crypto_box_easy(c, m, ctypes.c_ulonglong(len(m)), n, pk, sk) == 0
    return c.raw


def box_open(c, n, pk, sk):
    o = ctypes.create_string_buffer(len(c) - MAC)
    assert S.crypto_box_open_easy(o, c, ctypes.c_ulonglong(len(c)), n, pk, sk) == 0
    return o.raw


def b64e(b): return base64.b64encode(b).decode()
def b64d(s): return base64.b64decode(s)


def inc(n):
    o = bytearray(n); c = 1
    for i in range(len(o)):
        c += o[i]; o[i] = c & 0xFF; c >>= 8
    return bytes(o)


HOST_PK, HOST_SK = keypair()
# A list so a background thread can swap the "active database" mid-run; see below.
DBHASH = ["abc123deadbeef"]
ALTHASH = "fee1deadbeef99"
# KPXC_MOCK_HASH_SWITCH_AFTER=<seconds> flips the active database hash once, standing
# in for the user switching to a different vault in the KeePassXC GUI. Exercises
# `wait-db --changed`, which cannot rely on the database-unlocked broadcast because
# switching between two already-unlocked databases emits no signal.
_switch_after = os.environ.get("KPXC_MOCK_HASH_SWITCH_AFTER")
if _switch_after:
    def _switch():
        time.sleep(float(_switch_after))
        DBHASH[0] = ALTHASH
    threading.Thread(target=_switch, daemon=True).start()

# get-logins is URL-aware so the miss and multi-match paths are reachable:
#   https://box.example   -> one entry
#   https://multi.example -> two entries (choosing among matches)
#   anything else         -> errorCode 15, which the real KeePassXC returns for "no
#                            logins found" and which must surface as exit 6, not exit 0.
ENTRIES = {
    "https://box.example": [
        {"login": "admin", "name": "Box", "password": "p'q\"x y", "uuid": "u1"}],
    "https://multi.example": [
        {"login": "admin", "name": "Box prod", "password": "first-secret", "uuid": "u1"},
        {"login": "deploy", "name": "Box staging", "password": "second-secret", "uuid": "u2"}],
}
# When KPXC_MOCK_LOCKED is set, start with no database "open": the first
# get-databasehash returns errorCode 1 (as a locked/closed KeePassXC does), then a
# database-unlocked broadcast is sent shortly after so the agent's triggerUnlock
# wait succeeds and it retries. This exercises the unlock-on-locked/closed path.
LOCKED = [bool(os.environ.get("KPXC_MOCK_LOCKED"))]
DBGROUPS = {"groups": {"defaultGroup": "Root", "defaultGroupAlwaysAllow": False,
                       "groups": [{"name": "Root", "uuid": "r",
                                   "children": [{"name": "Servers", "uuid": "s", "children": []}]}]}}


def handle(conn):
    client_pk = [None]
    associated = [False]
    buf = [b""]  # bare-JSON receive buffer; messages have no delimiter

    def recv():
        # The real BrowserServer socket speaks bare JSON: parse the first
        # complete message out of the buffer, reading more only when needed
        # (messages can coalesce in one recv()).
        while True:
            if buf[0]:
                try:
                    text = buf[0].decode("utf-8")
                except UnicodeDecodeError:
                    text = None
                if text is not None:
                    stripped = text.lstrip()
                    try:
                        obj, idx = json.JSONDecoder().raw_decode(stripped)
                    except ValueError:
                        obj = None
                    else:
                        buf[0] = stripped[idx:].encode("utf-8")
                        return obj
            c = conn.recv(65536)
            if not c:
                return None
            buf[0] += c

    def send(obj):
        conn.sendall(json.dumps(obj).encode())

    def reply_encrypted(action, data, req_nonce):
        rn = inc(req_nonce)
        data["nonce"] = b64e(rn)
        ct = box(json.dumps(data).encode(), rn, client_pk[0], HOST_SK)
        send({"action": action, "message": b64e(ct), "nonce": b64e(rn)})

    while True:
        req = recv()
        if req is None:
            return
        action = req.get("action")
        if action == "change-public-keys":
            client_pk[0] = b64d(req["publicKey"])
            send({"action": action, "version": "2.7.0", "publicKey": b64e(HOST_PK), "success": "true"})
            continue
        rn = b64d(req["nonce"])
        inner = json.loads(box_open(b64d(req["message"]), rn, client_pk[0], HOST_SK))
        if action == "associate":
            reply_encrypted(action, {"hash": DBHASH[0], "version": "2.7.0", "success": "true", "id": "mock"}, rn)
        elif action == "test-associate":
            associated[0] = True
            reply_encrypted(action, {"version": "2.7.0", "hash": DBHASH[0], "id": "mock", "success": "true"}, rn)
        elif action == "get-databasehash":
            if LOCKED[0]:
                # Refuse while locked, then unlock shortly so the agent's
                # triggerUnlock wait wakes and retries on this same connection.
                send({"action": action, "errorCode": "1", "error": "Database not opened"})

                def _unlock():
                    time.sleep(0.3)
                    LOCKED[0] = False
                    try:
                        send({"action": "database-unlocked"})
                    except OSError:
                        pass
                threading.Thread(target=_unlock, daemon=True).start()
            else:
                reply_encrypted(action, {"action": "hash", "hash": DBHASH[0], "version": "2.7.0"}, rn)
        elif action == "get-logins":
            if not associated[0]:
                send({"action": action, "error": "association failed", "errorCode": "8"})
            else:
                found = ENTRIES.get(inner.get("url", ""))
                if not found:
                    send({"action": action, "error": "No logins found", "errorCode": "15"})
                else:
                    reply_encrypted(action, {"count": str(len(found)), "entries": found,
                                             "success": "true", "hash": DBHASH[0]}, rn)
        elif action == "get-totp":
            reply_encrypted(action, {"totp": "123456", "success": "true", "version": "2.7.0"}, rn)
        elif action == "generate-password":
            send({})  # empty ack frame, as the real KeePassXC does
            reply_encrypted(action, {"password": "Gen3r@ted-Long-Pass", "success": "true", "version": "2.7.0"}, rn)
        elif action == "set-login":
            reply_encrypted(action, {"error": "", "success": "true", "hash": DBHASH[0]}, rn)
        elif action == "get-database-groups":
            reply_encrypted(action, dict(DBGROUPS, success="true"), rn)
        elif action == "create-new-group":
            reply_encrypted(action, {"name": inner.get("groupName"), "uuid": "new-uuid", "success": "true"}, rn)
        elif action == "lock-database":
            send({"action": action, "errorCode": "1", "error": "Database not opened"})
        else:
            send({"action": action, "error": "unknown action", "errorCode": "11"})


def proxy_stdio(sock_path):
    """Stand in for keepassxc-proxy: native messaging on stdio, bare JSON on the socket."""
    upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    upstream.connect(sock_path)

    def read_frame():
        hdr = sys.stdin.buffer.read(4)
        if len(hdr) < 4:
            return None
        (length,) = struct.unpack("<I", hdr)
        payload = sys.stdin.buffer.read(length)
        return payload if len(payload) == length else None

    def relay(stdin_to_socket):
        try:
            if stdin_to_socket:
                while True:
                    frame = read_frame()
                    if frame is None:
                        break
                    upstream.sendall(frame)
            else:
                while True:
                    data = upstream.recv(65536)
                    if not data:
                        break
                    sys.stdout.buffer.write(struct.pack("<I", len(data)) + data)
                    sys.stdout.buffer.flush()
        except OSError:
            pass

    t = threading.Thread(target=relay, args=(True,), daemon=True)
    t.start()
    relay(False)
    t.join(timeout=1.0)


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--proxy-stdio":
        proxy_stdio(sys.argv[2])
        return
    path = sys.argv[1]
    if os.path.exists(path):
        os.unlink(path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path); srv.listen(5)
    sys.stderr.write("mock-kpxc: listening on %s\n" % path); sys.stderr.flush()
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
