#!/usr/bin/env python3
"""
kpxc_bridge.py - expose the local KeePassXC transport as a listening socket so it
can be reverse-forwarded over SSH (``ssh -R``) to a remote box.

This is the client-side half of the cross-SSH story. The agent runs on a remote
box where KeePassXC is NOT reachable; KeePassXC lives on the client the user sits
at. The client runs this bridge, ``ssh -R`` forwards its listening endpoint onto
the box, and ``kpxc-agent --socket <forwarded>`` on the box talks straight to it.

The bridge is a pure byte pump. It never decrypts or parses the protocol: each
accepted connection gets its own transport to the local KeePassXC (a direct unix
socket, or a ``keepassxc-proxy`` subprocess for the Windows named pipe), and bytes
are shuttled verbatim in both directions until either side closes. The crypto and
the per-connection ``test-associate`` stay end-to-end between the box's kpxc-agent
and KeePassXC - exactly as if they shared a machine.

Usage:
  kpxc_bridge.py --listen HOST:PORT  [--socket PATH | --exec CMD]
  kpxc_bridge.py --listen unix:/path [--socket PATH | --exec CMD]

``--socket`` / ``--exec`` pick how to reach the *local* KeePassXC and mirror the
channel's options; when neither is given a local unix socket is auto-resolved.
With ``--listen 127.0.0.1:0`` an ephemeral port is chosen and printed.

Requires: python3 (stdlib) and, transitively (via kpxc_channel), libsodium - it is
already present on a machine running KeePassXC.
"""

import os
import shlex
import signal
import socket
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kpxc_channel import SocketTransport, ExecTransport, resolve_socket  # noqa: E402

BUF = 65536


def die(msg):
    sys.stderr.write("kpxc-bridge: %s\n" % msg)
    sys.exit(1)


def make_transport(sock_path, exec_cmd):
    """Fresh transport to the local KeePassXC for one accepted connection."""
    if exec_cmd:
        return ExecTransport(shlex.split(exec_cmd))
    return SocketTransport(resolve_socket(sock_path))


def close_transport(t):
    sock = getattr(t, "sock", None)
    if sock is not None:
        # Closing the socket unblocks a recv() pending in the other direction.
        try:
            sock.close()
        except OSError:
            pass
        return
    proc = getattr(t, "proc", None)
    if proc is not None:
        # terminate() first: the proxy exiting EOFs its stdout, cleanly unblocking
        # a read1() in flight (closing the fd underneath it would race).
        try:
            proc.terminate()
        except OSError:
            pass
        for stream in (proc.stdin, proc.stdout):
            try:
                stream.close()
            except (OSError, ValueError):
                pass


def pump(read, write):
    """Copy read()->write() until EOF or error; swallow the teardown race."""
    try:
        while True:
            data = read(BUF)
            if not data:
                break
            write(data)
    except (OSError, ValueError):
        pass


def handle(conn, sock_path, exec_cmd):
    try:
        transport = make_transport(sock_path, exec_cmd)
    except SystemExit:
        # make_transport (via kpxc_channel) calls die() on failure; don't take
        # the whole bridge down for one bad connection.
        conn.close()
        return
    # Pump both directions concurrently. Whichever side closes first (normally the
    # box closing its connection after reading the reply, since KeePassXC keeps its
    # side open) trips `done`; we then tear down BOTH endpoints so the other
    # direction's blocked recv() returns and the transport is released.
    done = threading.Event()

    def direction(read, write):
        pump(read, write)
        done.set()

    threads = [
        threading.Thread(target=direction, args=(conn.recv, transport.send), daemon=True),
        threading.Thread(target=direction, args=(transport.recv, conn.sendall), daemon=True),
    ]
    for t in threads:
        t.start()
    done.wait()
    close_transport(transport)
    try:
        conn.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    conn.close()
    for t in threads:
        t.join(timeout=1.0)


def make_listener(spec):
    """Bind the listening endpoint. spec is 'unix:/path' or 'HOST:PORT'."""
    if spec.startswith("unix:"):
        path = spec[len("unix:"):]
        if not path:
            die("--listen unix: requires a path")
        if os.path.exists(path):
            os.unlink(path)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        srv.listen(16)
        return srv, "unix:%s" % path
    host, sep, port = spec.rpartition(":")
    if not sep:
        die("--listen expects HOST:PORT or unix:/path, got %r" % spec)
    try:
        port = int(port)
    except ValueError:
        die("--listen port must be a number, got %r" % port)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host or "127.0.0.1", port))
    srv.listen(16)
    bound_host, bound_port = srv.getsockname()[:2]
    return srv, "%s:%d" % (bound_host, bound_port)


def main():
    listen = None
    sock_path = None
    exec_cmd = None
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--listen":
            listen = argv[i + 1]; i += 2
        elif argv[i] == "--socket":
            sock_path = argv[i + 1]; i += 2
        elif argv[i] == "--exec":
            exec_cmd = argv[i + 1]; i += 2
        else:
            die("unknown argument: %s" % argv[i])
    if not listen:
        die("usage: kpxc_bridge.py --listen HOST:PORT|unix:/path [--socket PATH | --exec CMD]")

    srv, where = make_listener(listen)
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    sys.stderr.write("kpxc-bridge: listening on %s -> %s\n" %
                     (where, exec_cmd or sock_path or "auto socket"))
    sys.stderr.flush()
    # A line on stdout lets a parent capture the chosen (possibly ephemeral) port.
    sys.stdout.write(where + "\n")
    sys.stdout.flush()
    try:
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=handle, args=(conn, sock_path, exec_cmd),
                             daemon=True).start()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        srv.close()
        if where.startswith("unix:"):
            try:
                os.unlink(where[len("unix:"):])
            except OSError:
                pass


if __name__ == "__main__":
    main()
