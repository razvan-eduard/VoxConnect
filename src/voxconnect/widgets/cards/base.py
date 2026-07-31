"""Common QDockWidget shell for every dashboard card: a title bar with a
refresh button, and a content/empty/locked/error page stack. Subclasses
override `refresh()` and populate the content page via `clear_content()` /
`add_content_row()`, or `show_empty()`/`show_locked()`/`show_error()`."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

PAGE_CONTENT = 0
PAGE_EMPTY = 1
PAGE_LOCKED = 2
PAGE_ERROR = 3


class BaseCard(QDockWidget):
    def __init__(self, object_name: str, title: str, parent: QWidget | None = None):
        super().__init__(title, parent)
        self.setObjectName(object_name)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        title_bar = QWidget()
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(6, 2, 6, 2)
        title_layout.addWidget(QLabel(f"<b>{title}</b>"))
        title_layout.addStretch(1)
        refresh_button = QToolButton()
        refresh_button.setText("⟳")
        refresh_button.setToolTip("Refresh")
        refresh_button.clicked.connect(self.refresh)
        title_layout.addWidget(refresh_button)
        self.setTitleBarWidget(title_bar)

        self._stack = QStackedWidget()

        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.addStretch(1)

        self._empty_label = _centered_label()
        self._locked_label = _centered_label()

        error_page = QWidget()
        error_layout = QVBoxLayout(error_page)
        self._error_label = _centered_label()
        error_layout.addWidget(self._error_label)
        retry_button = QPushButton("Retry")
        retry_button.clicked.connect(self.refresh)
        error_layout.addWidget(retry_button)

        self._stack.addWidget(self._content_widget)  # PAGE_CONTENT
        self._stack.addWidget(self._empty_label)  # PAGE_EMPTY
        self._stack.addWidget(self._locked_label)  # PAGE_LOCKED
        self._stack.addWidget(error_page)  # PAGE_ERROR

        self.setWidget(self._stack)

    # -- page switching -------------------------------------------------------

    def show_content(self) -> None:
        self._stack.setCurrentIndex(PAGE_CONTENT)

    def show_empty(self, message: str) -> None:
        self._empty_label.setText(message)
        self._stack.setCurrentIndex(PAGE_EMPTY)

    def show_locked(self, message: str) -> None:
        self._locked_label.setText(message)
        self._stack.setCurrentIndex(PAGE_LOCKED)

    def show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._stack.setCurrentIndex(PAGE_ERROR)

    # -- content page helpers ---------------------------------------------------

    def clear_content(self) -> None:
        while self._content_layout.count() > 1:  # keep the trailing stretch
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def add_content_row(self, widget: QWidget) -> None:
        self._content_layout.insertWidget(self._content_layout.count() - 1, widget)

    def refresh(self) -> None:
        raise NotImplementedError


def _centered_label() -> QLabel:
    label = QLabel("")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    return label
