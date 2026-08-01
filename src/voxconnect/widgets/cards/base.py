"""Common QDockWidget shell for every dashboard card: a title bar with a
refresh button, an optional filter box, and a content/empty/locked/error page
stack (content is scrollable — cards no longer truncate to a fixed top-N).
Subclasses override `refresh()` and populate the content page via
`clear_content()` / `add_content_row()`, or `show_empty()`/`show_locked()`/
`show_error()`."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

PAGE_CONTENT = 0
PAGE_EMPTY = 1
PAGE_LOCKED = 2
PAGE_ERROR = 3


class ClickableRow(QFrame):
    """A row wrapper that makes its content selectable/openable, with an optional delete button
    alongside it. No frame border — a boxed outline around every single row reads as a
    spreadsheet, not a list; the click affordance comes from the pointing-hand cursor plus a QSS
    hover highlight instead (see resources/style.qss's `ClickableRow:hover` rule). The delete
    button is a real QToolButton child, not part of `content` — Qt routes its clicks to the
    button itself before they'd ever reach this row's own mousePressEvent, so it never triggers
    `clicked` (open) at the same time."""

    clicked = Signal()

    def __init__(self, content: QWidget, on_delete: Callable[[], None] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(content, 1)
        if on_delete is not None:
            delete_button = QToolButton()
            delete_button.setText("✕")
            delete_button.setToolTip("Delete")
            delete_button.setProperty("class", "danger")
            # QToolButton.clicked carries a `checked: bool` argument. Callers pass a
            # default-argument lambda to capture a per-row record (`lambda r=record: ...`) — since
            # that lambda *can* accept one positional argument, PySide hands it Qt's `checked`
            # value instead of using the default, silently replacing the captured record with a
            # bool. Calling on_delete() explicitly with zero arguments here shields every caller
            # from that gotcha instead of requiring each one to remember a `_checked=False` dummy
            # parameter (see media_card.py's _transport_button for the same idiom, applied inline).
            delete_button.clicked.connect(lambda _checked=False: on_delete())
            layout.addWidget(delete_button)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class BaseCard(QDockWidget):
    filter_changed = Signal(str)

    def __init__(
        self,
        object_name: str,
        title: str,
        parent: QWidget | None = None,
        *,
        on_add: Callable[[], None] | None = None,
        filterable: bool = False,
    ):
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
        if on_add is not None:
            add_button = QToolButton()
            add_button.setText("+")
            add_button.setToolTip("Add new")
            add_button.setProperty("class", "success")
            add_button.clicked.connect(lambda _checked=False: on_add())  # see the delete_button comment above
            title_layout.addWidget(add_button)
        refresh_button = QToolButton()
        refresh_button.setText("⟳")
        refresh_button.setToolTip("Refresh")
        refresh_button.setProperty("class", "warning")
        refresh_button.clicked.connect(self.refresh)
        title_layout.addWidget(refresh_button)
        self.setTitleBarWidget(title_bar)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        if filterable:
            self._filter_edit = QLineEdit()
            self._filter_edit.setPlaceholderText("Filter…")
            self._filter_edit.setClearButtonEnabled(True)
            self._filter_edit.textChanged.connect(self.filter_changed.emit)
            filter_row = QWidget()
            filter_layout = QHBoxLayout(filter_row)
            filter_layout.setContentsMargins(6, 6, 6, 0)
            filter_layout.addWidget(self._filter_edit)
            body_layout.addWidget(filter_row)
        else:
            self._filter_edit = None

        self._stack = QStackedWidget()

        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.addStretch(1)

        content_scroll = QScrollArea()
        content_scroll.setWidgetResizable(True)
        content_scroll.setFrameShape(QFrame.Shape.NoFrame)
        content_scroll.setWidget(self._content_widget)

        self._empty_label = _centered_label()
        self._locked_label = _centered_label()

        error_page = QWidget()
        error_layout = QVBoxLayout(error_page)
        self._error_label = _centered_label()
        error_layout.addWidget(self._error_label)
        retry_button = QPushButton("Retry")
        retry_button.clicked.connect(self.refresh)
        error_layout.addWidget(retry_button)

        self._stack.addWidget(content_scroll)  # PAGE_CONTENT
        self._stack.addWidget(self._empty_label)  # PAGE_EMPTY
        self._stack.addWidget(self._locked_label)  # PAGE_LOCKED
        self._stack.addWidget(error_page)  # PAGE_ERROR

        body_layout.addWidget(self._stack, 1)
        self.setWidget(body)

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

    def add_clickable_row(
        self, content: QWidget, on_click: Callable[[], None], on_delete: Callable[[], None] | None = None
    ) -> None:
        row = ClickableRow(content, on_delete=on_delete)
        row.clicked.connect(on_click)
        self.add_content_row(row)

    def filter_text(self) -> str:
        return self._filter_edit.text() if self._filter_edit is not None else ""

    def refresh(self) -> None:
        raise NotImplementedError


def _centered_label() -> QLabel:
    label = QLabel("")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    return label
