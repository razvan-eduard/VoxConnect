"""Webcam QR scanning, meant to run on a QThread (not polled from a QTimer —
`cv2.VideoCapture.read()` blocks for the duration of a frame grab, which
would stall the Qt event loop if called from the GUI thread).

Stop signaling uses a plain `threading.Event` rather than routing through
Qt's queued-signal mechanism: `start_scanning()` blocks the whole thread in a
loop, so the thread's own Qt event loop never runs until that loop exits —
a queued cross-thread call to `stop_scanning()` would never be delivered.
Setting a `threading.Event` is thread-safe and works regardless.
"""

from __future__ import annotations

import json
import threading

import cv2
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

REQUIRED_PAYLOAD_KEYS = {"ip", "port", "token", "key"}
DECODE_EVERY_N_FRAMES = 3


class QrScanWorker(QObject):
    frame_ready = Signal(QImage)
    qr_decoded = Signal(dict)
    decode_error = Signal(str)
    camera_error = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._stop_event = threading.Event()

    def stop_scanning(self) -> None:
        self._stop_event.set()

    def start_scanning(self, camera_index: int = 0) -> None:
        self._stop_event.clear()
        try:
            from pyzbar import pyzbar
        except ImportError as exc:
            self.camera_error.emit(f"QR decoding unavailable ({exc}) — use manual entry instead.")
            return

        capture = cv2.VideoCapture(camera_index)
        if not capture.isOpened():
            capture.release()
            self.camera_error.emit("No camera detected")
            return

        last_bad_payload: bytes | None = None
        frame_count = 0
        try:
            while not self._stop_event.is_set():
                ok, frame = capture.read()
                if not ok:
                    self.camera_error.emit("Camera read failed")
                    return
                self.frame_ready.emit(_to_qimage(frame))

                frame_count += 1
                if frame_count % DECODE_EVERY_N_FRAMES != 0:
                    continue
                codes = pyzbar.decode(frame)
                if not codes:
                    continue
                raw_bytes = codes[0].data
                payload = _decode_payload(raw_bytes)
                if payload is None:
                    if raw_bytes != last_bad_payload:
                        last_bad_payload = raw_bytes
                        self.decode_error.emit("That doesn't look like a VoxConnect pairing code")
                    continue
                self.qr_decoded.emit(payload)
                return
        finally:
            capture.release()


def _to_qimage(frame) -> QImage:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    height, width, channels = rgb.shape
    return QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888).copy()


def _decode_payload(raw_bytes: bytes) -> dict | None:
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not REQUIRED_PAYLOAD_KEYS.issubset(payload.keys()):
        return None
    return payload
