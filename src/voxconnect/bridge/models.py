"""JSON-shape models mirroring VoxApps' core/ipc contract (VoxCommand.kt /
VoxResult.kt) and its domain data classes (CalendarEntry, Expense, Note).

These are the exact wire shapes the bridge speaks — see core/ipc in VoxApps
for the source of truth. Kept as plain dataclasses with to_dict/from_dict
rather than a schema library, since the shape is small and fixed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


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


@dataclass
class CalendarEntry:
    id: int
    uid: str
    type: str  # EVENT | TASK
    title: str
    start_millis: int
    layer_id: int
    created_at: int
    updated_at: int
    description: str | None = None
    location: str | None = None
    end_millis: int | None = None
    all_day: bool = False
    completed: bool = False
    recurrence_frequency: str = "NONE"
    recurrence_until_millis: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "CalendarEntry":
        return cls(
            id=data["id"],
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
            layer_id=data["layerId"],
            created_at=data["createdAt"],
            updated_at=data["updatedAt"],
        )


@dataclass
class Expense:
    id: int
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
    category_id: int | None = None
    direction: str = "OUTGOING"  # OUTGOING | INCOMING
    receipt_image_name: str | None = None
    is_stub: bool = False
    source: str = "MANUAL"
    manually_edited: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "Expense":
        return cls(
            id=data["id"],
            uid=data["uid"],
            title=data.get("title"),
            total_amount=data["totalAmount"],
            currency_code=data["currencyCode"],
            vendor=data.get("vendor"),
            bank=data.get("bank"),
            location=data.get("location"),
            date_time=data["dateTime"],
            comments=data.get("comments"),
            category_id=data.get("categoryId"),
            direction=data.get("direction", "OUTGOING"),
            receipt_image_name=data.get("receiptImageName"),
            is_stub=data.get("isStub", False),
            created_at=data["createdAt"],
            updated_at=data["updatedAt"],
            source=data.get("source", "MANUAL"),
            manually_edited=data.get("manuallyEdited", False),
        )


@dataclass
class Note:
    id: int
    uid: str
    text: str
    created_at: int
    updated_at: int
    title: str | None = None
    category_id: int | None = None
    is_stub: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "Note":
        return cls(
            id=data["id"],
            uid=data["uid"],
            title=data.get("title"),
            text=data["text"],
            created_at=data["createdAt"],
            category_id=data.get("categoryId"),
            updated_at=data["updatedAt"],
            is_stub=data.get("isStub", False),
        )
