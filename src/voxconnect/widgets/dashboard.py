"""The main dashboard window: hosts one card per domain plus the Ask box.

This module starts as a placeholder (task 1 scaffold) and grows into the full
draggable card shell in a later pass (kickoff task 6).
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget
from PySide6.QtCore import Qt


class DashboardWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VoxConnect")
        self.resize(480, 360)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        placeholder = QLabel("VoxConnect dashboard — cards coming soon.")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(placeholder)

        self.setCentralWidget(central)
