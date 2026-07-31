from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from voxconnect.bridge.models import DOMAIN_NOTES, Note
from voxconnect.cache.store import CacheStore
from voxconnect.cache.sync import SyncEngine
from voxconnect.widgets.cards.base import BaseCard

TOP_N = 5


class NotesCard(BaseCard):
    def __init__(self, cache: CacheStore, sync_engine: SyncEngine, parent: QWidget | None = None):
        super().__init__("card_notes", "Recent Notes", parent)
        self._cache = cache
        self._sync_engine = sync_engine
        sync_engine.domain_synced.connect(self._on_domain_synced)
        sync_engine.domain_locked.connect(self._on_domain_locked)
        sync_engine.domain_error.connect(self._on_domain_error)
        self.render()

    def refresh(self) -> None:
        self._sync_engine.force_full_refresh(DOMAIN_NOTES)

    def _on_domain_synced(self, domain: str) -> None:
        if domain == DOMAIN_NOTES:
            self.render()

    def _on_domain_locked(self, domain: str, locked: bool) -> None:
        if domain == DOMAIN_NOTES and locked:
            self.show_locked("Phone locked — unlock Vox Notes to sync.")

    def _on_domain_error(self, domain: str, message: str) -> None:
        if domain == DOMAIN_NOTES:
            self.show_error(message)

    def render(self) -> None:
        entries = [Note.from_dict(raw) for raw in self._cache.get_entries(DOMAIN_NOTES)]
        recent = sorted(entries, key=lambda n: n.updated_at, reverse=True)[:TOP_N]

        self.clear_content()
        if not recent:
            self.show_empty("No recent notes.")
            return
        for note in recent:
            self.add_content_row(_build_row(note))
        self.show_content()


def _build_row(note: Note) -> QWidget:
    row = QWidget()
    layout = QVBoxLayout(row)
    layout.setContentsMargins(4, 2, 4, 2)
    title = note.title or (note.text[:60] if note.text else "(untitled)")
    layout.addWidget(QLabel(f"<b>{title}</b>"))
    if note.category_name:
        category_label = QLabel(note.category_name)
        category_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(category_label)
    return row
