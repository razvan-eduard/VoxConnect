"""Temporary local HTTP listener for the reversed pairing handshake.

The phone is the long-lived HTTP *server* for every request after pairing
(only it can reach Vox Commander and the other satellite apps over Android's
internal IPC bus) — so it can't simultaneously be the one waiting to be
found. Pairing instead works the other way: this app generates a fresh AES
key and stands up a one-shot local listener, encodes {ip, port, key} for
that listener into a QR, and the phone (scanning it with its own camera)
pushes its real credential to `POST /pair-complete` on that address. See
VoxApps' VoxConnectPairing.completeScannedPairing()/VoxConnectQrScanner for
the phone-side half of this handshake.

Uses stdlib `http.server` rather than pulling in a new HTTP framework for one
throwaway endpoint. `serve_forever()` runs on a daemon thread; the handler
runs on that same thread, so its Qt signal emissions cross back to the GUI
thread via the same auto-queuing AutoConnection pattern already used by
bridge/events.py and util/workers.py — no new threading pattern.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from PySide6.QtCore import QObject, Signal

from voxconnect.bridge import crypto
from voxconnect.settings import PairedDevice

PAIR_COMPLETE_PATH = "/pair-complete"


def _local_ip() -> str:
    """The machine's real LAN-facing address — 0.0.0.0 (what the listener
    binds to) isn't something the phone can dial. Doesn't actually send
    any packets; just asks the OS which local address it would use to
    reach a public one."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class _PairCompleteHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib-mandated method name
        if self.path != PAIR_COMPLETE_PATH:
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        plaintext = crypto.decrypt(self.server.pairing_key, body)
        if plaintext is None:
            self.send_response(400)
            self.end_headers()
            self.server.on_error("Failed to decrypt pairing push (bad key or tampered data).")
            return

        try:
            data = json.loads(plaintext)
            device = PairedDevice(
                device_id=data["deviceId"],
                key_base64=data["sessionKey"],
                host=self.client_address[0],
                port=int(data["port"]),
                label=data.get("label") or "Phone",
            )
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_response(400)
            self.end_headers()
            self.server.on_error(f"Malformed pairing push: {exc}")
            return

        self.send_response(200)
        self.end_headers()
        self.server.on_result(device)

    def log_message(self, format: str, *args: object) -> None:
        pass  # silence stdlib's default per-request stderr access log


class PairListener(QObject):
    pairing_received = Signal(object)  # PairedDevice
    pairing_error = Signal(str)

    def __init__(self, key: bytes, parent: QObject | None = None):
        super().__init__(parent)
        self._key = key
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> tuple[str, int]:
        server = HTTPServer(("0.0.0.0", 0), _PairCompleteHandler)
        server.pairing_key = self._key
        server.on_result = self._on_result
        server.on_error = self._on_error
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        return _local_ip(), server.server_address[1]

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _on_result(self, device: PairedDevice) -> None:
        self.pairing_received.emit(device)

    def _on_error(self, message: str) -> None:
        self.pairing_error.emit(message)
