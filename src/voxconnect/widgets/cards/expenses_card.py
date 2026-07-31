from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from voxconnect.bridge.models import DOMAIN_EXPENSES, Expense
from voxconnect.cache.store import CacheStore
from voxconnect.cache.sync import SyncEngine
from voxconnect.widgets.cards.base import BaseCard

TOP_N = 5


class ExpensesCard(BaseCard):
    def __init__(self, cache: CacheStore, sync_engine: SyncEngine, parent: QWidget | None = None):
        super().__init__("card_expenses", "Recent Expenses", parent)
        self._cache = cache
        self._sync_engine = sync_engine
        sync_engine.domain_synced.connect(self._on_domain_synced)
        sync_engine.domain_locked.connect(self._on_domain_locked)
        sync_engine.domain_error.connect(self._on_domain_error)
        self.render()

    def refresh(self) -> None:
        self._sync_engine.force_full_refresh(DOMAIN_EXPENSES)

    def _on_domain_synced(self, domain: str) -> None:
        if domain == DOMAIN_EXPENSES:
            self.render()

    def _on_domain_locked(self, domain: str, locked: bool) -> None:
        if domain == DOMAIN_EXPENSES and locked:
            self.show_locked("Phone locked — unlock Vox Expenses to sync.")

    def _on_domain_error(self, domain: str, message: str) -> None:
        if domain == DOMAIN_EXPENSES:
            self.show_error(message)

    def render(self) -> None:
        entries = [Expense.from_dict(raw) for raw in self._cache.get_entries(DOMAIN_EXPENSES)]
        recent = sorted(entries, key=lambda e: e.date_time, reverse=True)[:TOP_N]

        self.clear_content()
        if not recent:
            self.show_empty("No recent expenses.")
            return
        for expense in recent:
            self.add_content_row(_build_row(expense))
        self.show_content()


def _build_row(expense: Expense) -> QWidget:
    row = QWidget()
    layout = QVBoxLayout(row)
    layout.setContentsMargins(4, 2, 4, 2)
    label = expense.title or expense.vendor or f"{expense.total_amount:.2f} {expense.currency_code}"
    layout.addWidget(QLabel(f"<b>{label}</b>"))
    layout.addWidget(QLabel(f"{expense.total_amount:.2f} {expense.currency_code}"))
    if expense.category_name:
        category_label = QLabel(expense.category_name)
        category_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(category_label)
    if expense.line_items:
        items_label = QLabel(f"{len(expense.line_items)} line item(s)")
        items_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(items_label)
    return row
