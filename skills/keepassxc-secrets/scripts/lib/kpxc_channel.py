#!/usr/bin/env python3
"""
kpxc_channel.py - the minimal, protocol-agnostic encrypted channel to KeePassXC.

This is the ONLY non-shell component of keepassxc-cli-agent. It knows nothing
about individual KeePassXC actions; it just provides a libsodium "crypto_box"
secure pipe over the KeePassXC browser-integration unix socket. All protocol
semantics (which action, which fields, output formatting, identity) live in the
`kpxc-agent` bash script.

Two modes:

  kpxc_channel.py keypair
      Print a fresh base64 Curve25519 PUBLIC key on stdout (secret discarded).
      Used by bash to mint the persistent `idKey` for `associate`.

  kpxc_channel.py channel --socket PATH [--trigger-unlock]
      Perform the `change-public-keys` handshake, then for every line of
      plaintext inner-JSON read from stdin: encrypt it, send the envelope,
      receive + decrypt the reply, and print the decrypted inner-JSON as one
      line on stdout. The literal token @CLIENTKEY@ in an inner message is
      replaced with this session's client public key (used by `associate`).

Requires: python3 (stdlib) and libsodium (libsodium.so).
"""

import base64
import ctypes
import ctypes.util
import json
import os
import socket
import struct
import sys

PK_BYTES = 32     # crypto_box public key
SK_BYTES = 32     # crypto_box secret key
NONCE_BYTES = 24  # crypto_box nonce
MAC_BYTES = 16    # crypto_box_easy authentication tag


def die(msg):
    sys.stderr.write("kpxc-channel: %s\n" % msg)
    sys.exit(1)


def load_sodium():
    candidates = ["libsodium.so", "libsodium.so.26", "libsodium.so.23"]
    found = ctypes.util.find_library("sodium")
    if found:
        candidates.append(found)
    for name in candidates:
        try:
            lib = ctypes.CDLL(name)
        except OSError:
            continue
        if lib.sodium_init() < 0:
            die("sodium_init() failed")
        return lib
    die("libsodium not found - install it (e.g. apt install libsodium23 / "
        "dnf install libsodium / pacman -S libsodium / apk add libsodium)")


SODIUM = load_sodium()


def keypair():
    pk = ctypes.create_string_buffer(PK_BYTES)
    sk = ctypes.create_string_buffer(SK_BYTES)
    if SODIUM.crypto_box_keypair(pk, sk) != 0:
        die("crypto_box_keypair failed")
    return pk.raw, sk.raw


def box(message, nonce, peer_pk, my_sk):
    out = ctypes.create_string_buffer(len(message) + MAC_BYTES)
    rc = SODIUM.crypto_box_easy(
        out, message, ctypes.c_ulonglong(len(message)), nonce, peer_pk, my_sk)
    if rc != 0:
        die("encryption failed")
    return out.raw


def box_open(ciphertext, nonce, peer_pk, my_sk):
    if len(ciphertext) < MAC_BYTES:
        die("ciphertext too short")
    out = ctypes.create_string_buffer(len(ciphertext) - MAC_BYTES)
    rc = SODIUM.crypto_box_open_easy(
        out, ciphertext, ctypes.c_ulonglong(len(ciphertext)), nonce, peer_pk, my_sk)
    if rc != 0:
        die("decryption failed (wrong keys, tampered message, or KeePassXC reset the session)")
    return out.raw


def emit(obj):
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def b64e(raw):
    return base64.b64encode(raw).decode("ascii")


def b64d(text):
    return base64.b64decode(text)


def increment_nonce(nonce):
    """Little-endian increment with carry - matches libsodium / JS incrementedNonce."""
    out = bytearray(nonce)
    carry = 1
    for i in range(len(out)):
        carry += out[i]
        out[i] = carry & 0xFF
        carry >>= 8
    return bytes(out)


def resolve_socket(path):
    name = "org.keepassxc.KeePassXC.BrowserServer"
    if path:
        return path
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    bases = [runtime, os.environ.get("TMPDIR"), "/tmp"]
    # Flatpak places the socket under the app runtime dir.
    if runtime:
        bases.append(os.path.join(runtime, "app", "org.keepassxc.KeePassXC"))
    for base in bases:
        if base:
            candidate = os.path.join(base, name)
            if os.path.exists(candidate):
                return candidate
    # Nothing found; return the most likely path so connect() yields a clear error.
    return os.path.join(runtime or "/tmp", name)


class SocketTransport:
    """Direct AF_UNIX connection to a local KeePassXC browser-integration socket."""

    def __init__(self, sock_path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.sock.connect(sock_path)
        except OSError as exc:
            die("cannot connect to KeePassXC socket '%s': %s "
                "(is KeePassXC running with Browser Integration enabled?)" % (sock_path, exc))

    def send(self, data):
        self.sock.sendall(data)

    def recv(self, size):
        return self.sock.recv(size)


class ExecTransport:
    """Byte stream to KeePassXC via a relay subprocess's stdin/stdout.

    The relay is normally `keepassxc-proxy` (KeePassXC's own native-messaging
    proxy), which connects to the local socket / named pipe and speaks the same
    4-byte-length-framed protocol over stdio. This is how we cross the WSL->Windows
    boundary: WSL execs the Windows `keepassxc-proxy.exe`.
    """

    def __init__(self, argv):
        import subprocess
        try:
            self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        except OSError as exc:
            die("cannot launch relay %r: %s" % (argv, exc))

    def send(self, data):
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def recv(self, size):
        return self.proc.stdout.read1(size)


class Channel:
    def __init__(self, transport, trigger_unlock):
        self.trigger_unlock = trigger_unlock
        self.client_pk, self.client_sk = keypair()
        self.client_id = b64e(os.urandom(NONCE_BYTES))
        self.server_pk = None
        self.transport = transport

    def _recv_exact(self, n):
        chunks = []
        got = 0
        while got < n:
            chunk = self.transport.recv(n - got)
            if not chunk:
                die("connection closed by KeePassXC")
            chunks.append(chunk)
            got += len(chunk)
        return b"".join(chunks)

    def _send(self, obj):
        # KeePassXC's local transport uses native-messaging framing:
        # a 4-byte little-endian length prefix followed by the JSON payload.
        data = json.dumps(obj).encode("utf-8")
        self.transport.send(struct.pack("<I", len(data)) + data)

    def _recv_json(self):
        (length,) = struct.unpack("<I", self._recv_exact(4))
        return json.loads(self._recv_exact(length).decode("utf-8"))

    def handshake(self):
        nonce = os.urandom(NONCE_BYTES)
        request = {
            "action": "change-public-keys",
            "publicKey": b64e(self.client_pk),
            "nonce": b64e(nonce),
            "clientID": self.client_id,
        }
        if self.trigger_unlock:
            request["triggerUnlock"] = "true"
        self._send(request)
        response = self._recv_json()
        if response.get("success") != "true" or not response.get("publicKey"):
            die("key exchange failed: %s" % json.dumps(response))
        self.server_pk = b64d(response["publicKey"])

    def request(self, inner_line):
        if self.server_pk is None:
            self.handshake()

        inner_line = inner_line.replace("@CLIENTKEY@", b64e(self.client_pk))
        inner = json.loads(inner_line)

        nonce = os.urandom(NONCE_BYTES)
        ciphertext = box(inner_line.encode("utf-8"), nonce, self.server_pk, self.client_sk)
        envelope = {
            "action": inner["action"],
            "message": b64e(ciphertext),
            "nonce": b64e(nonce),
            "clientID": self.client_id,
        }
        if self.trigger_unlock:
            envelope["triggerUnlock"] = "true"
        if "requestID" in inner:  # used by generate-password; echoed at envelope level
            envelope["requestID"] = inner["requestID"]
        self._send(envelope)

        # Read the reply, skipping frames that are not the answer to this request:
        # unsolicited database-locked/unlocked signals, and the empty "{}" ack that
        # KeePassXC sends before some replies (e.g. generate-password emits {} first).
        response = None
        for _ in range(8):
            response = self._recv_json()
            if response.get("action") in ("database-locked", "database-unlocked") \
                    and "message" not in response:
                continue
            if "message" not in response and "error" not in response \
                    and "errorCode" not in response:
                continue  # empty/ack frame; the real reply follows
            break
        else:
            die("no usable reply from KeePassXC")

        if "message" not in response or "nonce" not in response:
            # Error envelope (e.g. errorCode/error) - hand it to bash verbatim.
            emit(response)
            return

        resp_nonce = b64d(response["nonce"])
        if resp_nonce != increment_nonce(nonce):
            die("nonce verification failed (possible replay or session mix-up)")
        plaintext = box_open(b64d(response["message"]), resp_nonce, self.server_pk, self.client_sk)
        # Emit one compact line per reply so the caller can read several in order
        # (KeePassXC pretty-prints its JSON, which would span multiple lines).
        emit(json.loads(plaintext.decode("utf-8")))


def run_channel(argv):
    sock_path = None
    exec_cmd = None
    trigger_unlock = False
    i = 0
    while i < len(argv):
        if argv[i] == "--socket":
            sock_path = argv[i + 1]
            i += 2
        elif argv[i] == "--exec":
            exec_cmd = argv[i + 1]
            i += 2
        elif argv[i] == "--trigger-unlock":
            trigger_unlock = True
            i += 1
        else:
            die("unknown channel argument: %s" % argv[i])
    if exec_cmd:
        import shlex
        transport = ExecTransport(shlex.split(exec_cmd))
    else:
        transport = SocketTransport(resolve_socket(sock_path))
    channel = Channel(transport, trigger_unlock)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        channel.request(line)
        sys.stdout.flush()


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "keypair":
        pk, _sk = keypair()
        print(b64e(pk))
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "channel":
        run_channel(sys.argv[2:])
        return
    die("usage: kpxc_channel.py {keypair | channel [--socket PATH | --exec CMD] [--trigger-unlock]}")


if __name__ == "__main__":
    main()
