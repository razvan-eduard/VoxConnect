"""JSON-shape models mirroring VoxApps' core/ipc contract (VoxCommand.kt /
VoxResult.kt) and its domain data classes (CalendarEntry, Expense, Note).

These are the exact wire shapes the bridge speaks — see core/ipc in VoxApps
for the source of truth. Kept as plain dataclasses with to_dict/from_dict
rather than a schema library, since the shape is small and fixed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


# VoxCommand.op values
OP_CREATE = "create"
OP_READ = "read"
OP_PING = "ping"
OP_EXPORT = "export"
OP_IMPORT = "import"
OP_GET_SCHEMA = "get_schema"
OP_SYNC_EXPORT = "sync_export"
OP_SYNC_MERGE = "sync_merge"
OP_MEDIA_CONTROL = "media_control"

# VoxCommand.exportScope values
EXPORT_SCOPE_SETTINGS = "settings"
EXPORT_SCOPE_DATA = "data"
EXPORT_SCOPE_BOTH = "both"

DOMAIN_NOTES = "notes"
DOMAIN_CALENDAR = "calendar"
DOMAIN_EXPENSES = "expenses"


@dataclass
class VoxCommand:
    op: str
    text: str | None = None
    title: str | None = None
    category: str | None = None
    limit: int | None = None
    domain: str | None = None
    export_scope: str | None = None
    include_secrets: bool = False
    include_photos: bool = False
    date_from: int | None = None
    date_to: int | None = None
    since: int | None = None
    scope_names: list[str] | None = None
    media_action: str | None = None

    def to_dict(self) -> dict:
        d = {
            "op": self.op,
            "text": self.text,
            "title": self.title,
            "category": self.category,
            "limit": self.limit,
            "domain": self.domain,
            "exportScope": self.export_scope,
            "includeSecrets": self.include_secrets,
            "includePhotos": self.include_photos,
            "dateFrom": self.date_from,
            "dateTo": self.date_to,
            "since": self.since,
            "scopeNames": self.scope_names,
            "mediaAction": self.media_action,
        }
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class VoxResult:
    ok: bool
    text: str
    attachment_uri: str | None = None
    secondary_attachment_uri: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "VoxResult":
        return cls(
            ok=bool(data.get("ok", False)),
            text=data.get("text", ""),
            attachment_uri=data.get("attachmentUri"),
            secondary_attachment_uri=data.get("secondaryAttachmentUri"),
        )


@dataclass
class AppInfo:
    package_name: str
    label: str
    domain: str | None
    actions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "AppInfo":
        return cls(
            package_name=data.get("packageName", ""),
            label=data.get("label", ""),
            domain=data.get("domain"),
            actions=list(data.get("actions", [])),
        )


# Expense.direction wire values (lowercase — NOT the raw Kotlin enum name)
DIRECTION_OUTGOING = "outgoing"
DIRECTION_INCOMING = "incoming"

# VoxResult.text strings for a biometric-locked domain (fixed, one per domain,
# not a machine-readable error code — see bridge/client.py module docstring).
LOCKED_MESSAGES = {
    DOMAIN_NOTES: "Notele sunt blocate. Deblochează aplicația.",
    DOMAIN_CALENDAR: "Calendarul este blocat. Deblochează aplicația.",
    DOMAIN_EXPENSES: "Cheltuielile sunt blocate. Deblochează aplicația.",
}


def is_locked(domain: str, result: VoxResult) -> bool:
    return not result.ok and result.text == LOCKED_MESSAGES.get(domain)


@dataclass
class Tombstone:
    uid: str
    deleted_at: int

    @classmethod
    def from_dict(cls, data: dict) -> "Tombstone":
        return cls(uid=data["uid"], deleted_at=data["deletedAt"])


@dataclass
class SyncResult:
    """The parsed envelope of a sync_export/sync_merge VoxResult.text — the
    raw wire dicts for `entries` (still domain-shaped, parsed further by
    CalendarEntry/Expense/Note.from_dict) plus the uid/deletedAt tombstones."""

    entries: list[dict]
    tombstones: list[Tombstone]

    @classmethod
    def from_json_text(cls, text: str) -> "SyncResult":
        data = json.loads(text)
        return cls(
            entries=list(data.get("entries", [])),
            tombstones=[Tombstone.from_dict(t) for t in data.get("tombstones", [])],
        )


@dataclass
class CalendarEntry:
    """sync_export shape — NOT the app-internal Room entity (no numeric id,
    layer travels by name)."""

    uid: str
    type: str  # EVENT | TASK
    title: str
    start_millis: int
    created_at: int
    updated_at: int
    description: str | None = None
    location: str | None = None
    end_millis: int | None = None
    all_day: bool = False
    completed: bool = False
    recurrence_frequency: str = "NONE"
    recurrence_until_millis: int | None = None
    layer_name: str | None = None
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "CalendarEntry":
        return cls(
            uid=data["uid"],
            type=data["type"],
            title=data["title"],
            description=data.get("description"),
            location=data.get("location"),
            start_millis=data["startMillis"],
            end_millis=data.get("endMillis"),
            all_day=data.get("allDay", False),
            completed=data.get("completed", False),
            recurrence_frequency=data.get("recurrenceFrequency", "NONE"),
            recurrence_until_millis=data.get("recurrenceUntilMillis"),
            layer_name=data.get("layerName"),
            tags=list(data.get("tags", [])),
            created_at=data["createdAt"],
            updated_at=data["updatedAt"],
        )


@dataclass
class ExpenseLineItem:
    """No uid/updatedAt of its own — travels with the parent expense, no
    independent sync identity."""

    name: str
    quantity: float
    unit_price: float
    position: int
    net_amount: float | None = None
    vat_amount: float | None = None
    gross_amount: float | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ExpenseLineItem":
        return cls(
            name=data["name"],
            quantity=data["quantity"],
            unit_price=data["unitPrice"],
            position=data["position"],
            net_amount=data.get("netAmount"),
            vat_amount=data.get("vatAmount"),
            gross_amount=data.get("grossAmount"),
        )


@dataclass
class Expense:
    """sync_export shape — category travels by name, direction is the
    lowercase wire value (DIRECTION_OUTGOING/DIRECTION_INCOMING), not the raw
    Kotlin enum name."""

    uid: str
    total_amount: float
    currency_code: str
    date_time: int
    created_at: int
    updated_at: int
    title: str | None = None
    vendor: str | None = None
    bank: str | None = None
    location: str | None = None
    comments: str | None = None
    category_name: str | None = None
    direction: str = DIRECTION_OUTGOING
    receipt_image_name: str | None = None
    is_stub: bool = False
    line_items: list[ExpenseLineItem] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Expense":
        return cls(
            uid=data["uid"],
            title=data.get("title"),
            total_amount=data["totalAmount"],
            currency_code=data["currencyCode"],
            vendor=data.get("vendor"),
            bank=data.get("bank"),
            location=data.get("location"),
            date_time=data["dateTime"],
            comments=data.get("comments"),
            category_name=data.get("categoryName"),
            direction=data.get("direction", DIRECTION_OUTGOING),
            receipt_image_name=data.get("receiptImageName"),
            is_stub=data.get("isStub", False),
            created_at=data["createdAt"],
            updated_at=data["updatedAt"],
            line_items=[ExpenseLineItem.from_dict(i) for i in data.get("lineItems", [])],
        )


@dataclass
class Note:
    """sync_export shape — category travels by name; no isStub field (unlike
    Calendar/Expenses)."""

    uid: str
    text: str
    created_at: int
    updated_at: int
    title: str | None = None
    category_name: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "Note":
        return cls(
            uid=data["uid"],
            title=data.get("title"),
            text=data["text"],
            category_name=data.get("categoryName"),
            created_at=data["createdAt"],
            updated_at=data["updatedAt"],
        )


@dataclass
class NowPlaying:
    playing: bool
    package_name: str | None = None
    title: str | None = None
    artist: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "NowPlaying":
        return cls(
            playing=bool(data.get("playing", False)),
            package_name=data.get("packageName"),
            title=data.get("title"),
            artist=data.get("artist"),
        )
