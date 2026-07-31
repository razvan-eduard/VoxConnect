"""QR-pairing dialog: webcam scan (primary) with a manual-entry fallback
(paste-JSON, or four individual fields) for machines with no camera."""

from __future__ import annotations

import json
import socket

from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from voxconnect import settings
from voxconnect.bridge.client import BridgeClient
from voxconnect.pairing.scanner import QrScanWorker
from voxconnect.settings import PairedDevice
from voxconnect.util.workers import run_in_background

REQUIRED_PAYLOAD_KEYS = {"ip", "port", "token", "key"}


def _friendly_pair_error(message: str) -> str:
    lowered = message.lower()
    if "400" in message or "404" in message:
        return "Pairing was rejected — the code may have expired. Generate a new one on the phone and try again."
    if "connect" in lowered or "timeout" in lowered or "timed out" in lowered:
        return f"Could not reach the phone — check it's on the same Wi-Fi.\n({message})"
    return f"Pairing failed: {message}"


class PairingWizard(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Pair with your phone")
        self.resize(420, 460)

        self._qr_payload: dict | None = None
        self._paired_device: PairedDevice | None = None
        self._scan_thread: QThread | None = None
        self._worker: QrScanWorker | None = None

        layout = QVBoxLayout(self)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_scan_tab(), "Scan QR Code")
        tabs.addTab(self._build_manual_tab(), "Enter manually")
        layout.addWidget(tabs)

        label_row = QHBoxLayout()
        label_row.addWidget(QLabel("Device label:"))
        self._label_edit = QLineEdit(socket.gethostname())
        label_row.addWidget(self._label_edit)
        layout.addLayout(label_row)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        buttons = QDialogButtonBox()
        self._pair_button = buttons.addButton("Pair", QDialogButtonBox.ButtonRole.AcceptRole)
        self._pair_button.setEnabled(False)
        self._pair_button.clicked.connect(self._on_pair_clicked)
        cancel_button = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self._start_camera()

    # -- tab construction ---------------------------------------------------

    def _build_scan_tab(self) -> QWidget:
        tab = QWidget(self)
        tab_layout = QVBoxLayout(tab)
        self._preview_label = QLabel("Starting camera…")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumSize(320, 240)
        tab_layout.addWidget(self._preview_label)
        self._scan_status_label = QLabel("")
        self._scan_status_label.setWordWrap(True)
        tab_layout.addWidget(self._scan_status_label)
        self._retry_camera_button = QPushButton("Retry camera")
        self._retry_camera_button.clicked.connect(self._start_camera)
        self._retry_camera_button.hide()
        tab_layout.addWidget(self._retry_camera_button)
        return tab

    def _build_manual_tab(self) -> QWidget:
        tab = QWidget(self)
        tab_layout = QVBoxLayout(tab)
        tab_layout.addWidget(QLabel("Paste the pairing code JSON:"))
        self._paste_edit = QPlainTextEdit()
        self._paste_edit.setPlaceholderText('{"ip": "...", "port": 8787, "token": "...", "key": "..."}')
        self._paste_edit.textChanged.connect(self._refresh_pair_enabled)
        tab_layout.addWidget(self._paste_edit)

        tab_layout.addWidget(QLabel("…or enter fields individually:"))
        form = QFormLayout()
        self._ip_edit = QLineEdit()
        self._port_edit = QLineEdit()
        self._token_edit = QLineEdit()
        self._key_edit = QLineEdit()
        for edit in (self._ip_edit, self._port_edit, self._token_edit, self._key_edit):
            edit.textChanged.connect(self._refresh_pair_enabled)
        form.addRow("IP:", self._ip_edit)
        form.addRow("Port:", self._port_edit)
        form.addRow("Token:", self._token_edit)
        form.addRow("Key:", self._key_edit)
        tab_layout.addLayout(form)
        return tab

    # -- camera lifecycle -----------------------------------------------------

    def _start_camera(self) -> None:
        self._stop_camera()
        self._retry_camera_button.hide()
        self._scan_status_label.setText("")
        self._preview_label.setText("Starting camera…")

        self._worker = QrScanWorker()
        self._scan_thread = QThread(self)
        self._worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(lambda: self._worker.start_scanning(0))
        self._worker.frame_ready.connect(self._on_frame_ready)
        self._worker.qr_decoded.connect(self._on_qr_decoded)
        self._worker.decode_error.connect(self._on_decode_error)
        self._worker.camera_error.connect(self._on_camera_error)
        self._scan_thread.start()

    def _stop_camera(self) -> None:
        if self._worker is not None:
            self._worker.stop_scanning()
        if self._scan_thread is not None:
            self._scan_thread.quit()
            self._scan_thread.wait(2000)
        self._worker = None
        self._scan_thread = None

    def _on_frame_ready(self, image: QImage) -> None:
        target_w = self._preview_label.width() or 320
        target_h = self._preview_label.height() or 240
        pixmap = QPixmap.fromImage(image).scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_label.setPixmap(pixmap)

    def _on_qr_decoded(self, payload: dict) -> None:
        self._qr_payload = payload
        self._scan_status_label.setText("QR code detected — press Pair.")
        self._refresh_pair_enabled()

    def _on_decode_error(self, message: str) -> None:
        self._scan_status_label.setText(message)

    def _on_camera_error(self, message: str) -> None:
        self._preview_label.setText(message)
        self._scan_status_label.setText('Use the "Enter manually" tab instead, or retry the camera.')
        self._retry_camera_button.show()

    # -- payload / pairing ----------------------------------------------------

    def _manual_payload(self) -> dict | None:
        paste_text = self._paste_edit.toPlainText().strip()
        if paste_text:
            try:
                payload = json.loads(paste_text)
            except json.JSONDecodeError:
                return None
            if isinstance(payload, dict) and REQUIRED_PAYLOAD_KEYS.issubset(payload.keys()):
                return payload
            return None

        ip = self._ip_edit.text().strip()
        port_text = self._port_edit.text().strip()
        token = self._token_edit.text().strip()
        key = self._key_edit.text().strip()
        if not (ip and port_text and token and key):
            return None
        try:
            port = int(port_text)
        except ValueError:
            return None
        return {"ip": ip, "port": port, "token": token, "key": key}

    def _current_payload(self) -> dict | None:
        return self._qr_payload or self._manual_payload()

    def _refresh_pair_enabled(self) -> None:
        self._pair_button.setEnabled(self._current_payload() is not None)

    def _on_pair_clicked(self) -> None:
        payload = self._current_payload()
        if payload is None:
            return
        label = self._label_edit.text().strip() or socket.gethostname()
        self._pair_button.setEnabled(False)
        self._status_label.setText("Pairing…")

        def do_pair() -> PairedDevice:
            return BridgeClient.pair(
                host=str(payload["ip"]),
                port=int(payload["port"]),
                token=str(payload["token"]),
                key_base64=str(payload["key"]),
                label=label,
            )

        run_in_background(do_pair, on_result=self._on_pair_success, on_error=self._on_pair_error)

    def _on_pair_success(self, device: PairedDevice) -> None:
        settings.save_paired_device(device)
        self._paired_device = device
        self._stop_camera()
        self.accept()

    def _on_pair_error(self, message: str) -> None:
        self._status_label.setText(_friendly_pair_error(message))
        self._refresh_pair_enabled()

    def paired_device(self) -> PairedDevice | None:
        return self._paired_device

    def reject(self) -> None:
        self._stop_camera()
        super().reject()
