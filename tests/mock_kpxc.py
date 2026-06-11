#!/usr/bin/env python3
"""Mock KeePassXC BrowserServer for offline end-to-end testing of kpxc-agent.

Implements the server half of the protocol faithfully enough to exercise the real
code paths: native-messaging length framing, the crypto_box handshake, per-connection
association (get-logins refuses until test-associate has run on the connection), and
the empty-ack frame that precedes a generate-password reply. Listens on an AF_UNIX
socket (argv[1]).
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
DBHASH = "abc123deadbeef"
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

    def recv():
        hdr = b""
        while len(hdr) < 4:
            c = conn.recv(4 - len(hdr))
            if not c: return None
            hdr += c
        (length,) = struct.unpack("<I", hdr)
        buf = b""
        while len(buf) < length:
            c = conn.recv(length - len(buf))
            if not c: return None
            buf += c
        return json.loads(buf)

    def send(obj):
        raw = json.dumps(obj).encode()
        conn.sendall(struct.pack("<I", len(raw)) + raw)

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
            reply_encrypted(action, {"hash": DBHASH, "version": "2.7.0", "success": "true", "id": "mock"}, rn)
        elif action == "test-associate":
            associated[0] = True
            reply_encrypted(action, {"version": "2.7.0", "hash": DBHASH, "id": "mock", "success": "true"}, rn)
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
                reply_encrypted(action, {"action": "hash", "hash": DBHASH, "version": "2.7.0"}, rn)
        elif action == "get-logins":
            if not associated[0]:
                send({"action": action, "error": "association failed", "errorCode": "8"})
            else:
                reply_encrypted(action, {"count": "1", "entries": [
                    {"login": "admin", "name": "Box", "password": "p'q\"x y", "uuid": "u1"}],
                    "success": "true", "hash": DBHASH}, rn)
        elif action == "get-totp":
            reply_encrypted(action, {"totp": "123456", "success": "true", "version": "2.7.0"}, rn)
        elif action == "generate-password":
            send({})  # empty ack frame, as the real KeePassXC does
            reply_encrypted(action, {"password": "Gen3r@ted-Long-Pass", "success": "true", "version": "2.7.0"}, rn)
        elif action == "set-login":
            reply_encrypted(action, {"error": "", "success": "true", "hash": DBHASH}, rn)
        elif action == "get-database-groups":
            reply_encrypted(action, dict(DBGROUPS, success="true"), rn)
        elif action == "create-new-group":
            reply_encrypted(action, {"name": inner.get("groupName"), "uuid": "new-uuid", "success": "true"}, rn)
        elif action == "lock-database":
            send({"action": action, "errorCode": "1", "error": "Database not opened"})
        else:
            send({"action": action, "error": "unknown action", "errorCode": "11"})


def main():
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
