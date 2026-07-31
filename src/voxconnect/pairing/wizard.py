"""QR-pairing dialog: this app generates and displays the QR (plus the same
values as a manually-typeable fallback); the phone scans it with its own
camera and pushes its credential back. See pairing/listener.py for the
handshake this dialog drives. Pairing completes automatically once that push
arrives — there's nothing for the user to submit on this side."""

from __future__ import annotations

import io
import json

import qrcode
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from voxconnect import settings
from voxconnect.bridge import crypto
from voxconnect.pairing.listener import PairListener
from voxconnect.settings import PairedDevice

TIMEOUT_MS = 5 * 60 * 1000
QR_SIZE = 280


def _build_qr_pixmap(text: str) -> QPixmap:
    image = qrcode.make(text)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    pixmap = QPixmap()
    pixmap.loadFromData(buffer.getvalue(), "PNG")
    return pixmap.scaled(
        QR_SIZE, QR_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )


def _read_only_field() -> QLineEdit:
    field = QLineEdit()
    field.setReadOnly(True)
    return field


class PairingWizard(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Pair with your phone")
        self.resize(380, 540)

        self._paired_device: PairedDevice | None = None
        self._listener: PairListener | None = None

        layout = QVBoxLayout(self)

        instructions = QLabel(
            'Open Vox Hub → Settings → VoxConnect → "Pair new device" and scan this '
            "code with your phone's camera."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setMinimumSize(QR_SIZE, QR_SIZE)
        layout.addWidget(self._qr_label)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)

        layout.addWidget(QLabel("Can't scan? Enter these manually:"))
        form = QFormLayout()
        self._ip_field = _read_only_field()
        self._port_field = _read_only_field()
        self._key_field = _read_only_field()
        form.addRow("IP:", self._ip_field)
        form.addRow("Port:", self._port_field)
        form.addRow("Key:", self._key_field)
        layout.addLayout(form)

        self._regenerate_button = QPushButton("Generate new code")
        self._regenerate_button.clicked.connect(self._start_pairing_attempt)
        self._regenerate_button.hide()
        layout.addWidget(self._regenerate_button)

        buttons = QDialogButtonBox()
        cancel_button = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.setInterval(TIMEOUT_MS)
        self._timeout_timer.timeout.connect(self._on_timeout)

        self._start_pairing_attempt()

    def _start_pairing_attempt(self) -> None:
        self._stop_listener()
        self._regenerate_button.hide()
        self._status_label.setText("Waiting for your phone to scan the code…")

        key = crypto.generate_key()
        self._listener = PairListener(key, self)
        self._listener.pairing_received.connect(self._on_pairing_received)
        self._listener.pairing_error.connect(self._on_pairing_error)
        host, port = self._listener.start()

        key_base64 = crypto.key_to_base64(key)
        payload = {"ip": host, "port": port, "key": key_base64}
        self._qr_label.setPixmap(_build_qr_pixmap(json.dumps(payload)))
        self._ip_field.setText(host)
        self._port_field.setText(str(port))
        self._key_field.setText(key_base64)

        self._timeout_timer.start()

    def _stop_listener(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._timeout_timer.stop()

    def _on_pairing_received(self, device: PairedDevice) -> None:
        settings.save_paired_device(device)
        self._paired_device = device
        self._stop_listener()
        self.accept()

    def _on_pairing_error(self, message: str) -> None:
        self._status_label.setText(message)

    def _on_timeout(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._status_label.setText("Timed out waiting for your phone. Generate a new code and try again.")
        self._regenerate_button.show()

    def paired_device(self) -> PairedDevice | None:
        return self._paired_device

    def reject(self) -> None:
        self._stop_listener()
        super().reject()
