"""QR-pairing dialog: this app generates and displays the QR (plus the same
values as a manually-typeable fallback); the phone scans it with its own
camera and pushes its credential back. See pairing/listener.py for the
handshake this dialog drives. Pairing completes automatically once that push
arrives — there's nothing for the user to submit on this side.

Starting the temporary listener (socket bind, thread spawn, and on some
platforms a first-run OS firewall permission prompt) runs in the background
via run_in_background rather than inline in __init__ — doing it inline would
block the dialog's very first paint, so the window would sit fully blank
until it finished instead of showing a loading state right away.
"""

from __future__ import annotations

import io
import json
import socket

import qrcode
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from voxconnect import settings
from voxconnect.bridge import crypto
from voxconnect.pairing.listener import PairListener
from voxconnect.settings import PairedDevice
from voxconnect.util.workers import run_in_background

TIMEOUT_MS = 5 * 60 * 1000
QR_SIZE = 280

PAGE_LOADING = 0
PAGE_READY = 1


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


def _copyable_row(field: QLineEdit) -> QWidget:
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(field)
    copy_button = QPushButton("Copy")
    copy_button.setFixedWidth(56)
    copy_button.clicked.connect(lambda: QApplication.clipboard().setText(field.text()))
    row.addWidget(copy_button)
    return container


class PairingWizard(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Pair with your phone")
        self.resize(420, 640)

        self._paired_device: PairedDevice | None = None
        self._listener: PairListener | None = None

        layout = QVBoxLayout(self)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_loading_page())
        self._stack.addWidget(self._build_ready_page())
        layout.addWidget(self._stack)

        buttons = QDialogButtonBox()
        cancel_button = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.setInterval(TIMEOUT_MS)
        self._timeout_timer.timeout.connect(self._on_timeout)

        self._start_pairing_attempt()

    # -- page construction ----------------------------------------------------

    def _build_loading_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.addStretch(1)
        progress = QProgressBar()
        progress.setRange(0, 0)  # indeterminate/busy animation
        page_layout.addWidget(progress)
        label = QLabel("Generating pairing code…")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page_layout.addWidget(label)
        page_layout.addStretch(1)
        return page

    def _build_ready_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)

        scan_group = QGroupBox("Scan with your phone")
        scan_layout = QVBoxLayout(scan_group)
        instructions = QLabel(
            'Open Vox Hub → Settings → VoxConnect → "Pair new device" and scan this '
            "code with your phone's camera."
        )
        instructions.setWordWrap(True)
        scan_layout.addWidget(instructions)

        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setMinimumSize(QR_SIZE, QR_SIZE)
        self._qr_label.setStyleSheet("background-color: white; border: 1px solid palette(mid);")
        scan_layout.addWidget(self._qr_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scan_layout.addWidget(self._status_label)

        page_layout.addWidget(scan_group)

        manual_group = QGroupBox("Can't scan? Enter these manually")
        form = QFormLayout(manual_group)
        self._ip_field = _read_only_field()
        self._port_field = _read_only_field()
        self._key_field = _read_only_field()
        form.addRow("IP:", _copyable_row(self._ip_field))
        form.addRow("Port:", _copyable_row(self._port_field))
        form.addRow("Key:", _copyable_row(self._key_field))
        page_layout.addWidget(manual_group)

        self._regenerate_button = QPushButton("Generate new code")
        self._regenerate_button.clicked.connect(self._start_pairing_attempt)
        self._regenerate_button.hide()
        page_layout.addWidget(self._regenerate_button)

        return page

    # -- pairing attempt lifecycle ------------------------------------------

    def _start_pairing_attempt(self) -> None:
        self._stop_listener()
        self._regenerate_button.hide()
        self._stack.setCurrentIndex(PAGE_LOADING)

        key = crypto.generate_key()
        listener = PairListener(key, self)
        listener.pairing_received.connect(self._on_pairing_received)
        listener.pairing_error.connect(self._on_pairing_error)
        self._listener = listener

        def do_start() -> tuple[str, int]:
            return listener.start()

        def on_result(host_port: tuple[str, int]) -> None:
            if listener is not self._listener:
                listener.stop()  # superseded by a cancel/regenerate while this was starting
                return
            host, port = host_port
            key_base64 = crypto.key_to_base64(key)
            # This machine's hostname rides along so Hub can show a real name for the paired PC
            # (renamable afterward) instead of a hardcoded "PC" label — see VoxConnectPairing.kt
            # on the Android side, which reads this same "hostname" key.
            payload = {"ip": host, "port": port, "key": key_base64, "hostname": socket.gethostname()}
            self._qr_label.setPixmap(_build_qr_pixmap(json.dumps(payload)))
            self._ip_field.setText(host)
            self._port_field.setText(str(port))
            self._key_field.setText(key_base64)
            self._status_label.setText("Waiting for your phone to scan the code…")
            self._stack.setCurrentIndex(PAGE_READY)
            self._timeout_timer.start()

        def on_error(message: str) -> None:
            if listener is not self._listener:
                return
            self._status_label.setText(f"Couldn't start the pairing listener: {message}")
            self._stack.setCurrentIndex(PAGE_READY)
            self._regenerate_button.show()

        run_in_background(do_start, on_result=on_result, on_error=on_error)

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
