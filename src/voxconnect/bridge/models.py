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
OP_GET_FIELD_SCHEMA = "get_field_schema"

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


# FormField.type values — see VoxFormSchema.kt (core/ipc) for the wire-side source of truth.
FIELD_TYPE_TEXT = "text"
FIELD_TYPE_NUMBER = "number"
FIELD_TYPE_DATETIME = "datetime"
FIELD_TYPE_BOOL = "bool"
FIELD_TYPE_ENUM = "enum"
FIELD_TYPE_CATEGORY = "category"
FIELD_TYPE_TAGS = "tags"
FIELD_TYPE_LIST = "list"
FIELD_TYPE_READONLY = "readonly"


@dataclass
class FormField:
    """One editable field of a domain's record type, as advertised by OP_GET_FIELD_SCHEMA. `options`
    holds fixed choices for `enum` fields or the satellite's live category/layer names for
    `category` fields — both rendered as a QComboBox, the distinction is purely descriptive.
    `item_fields` is only present for `type == "list"` (e.g. an expense's line items) and describes
    each repeated row's own fields, recursively — nesting never goes deeper than one level in
    practice, so `FormField` doesn't bother forbidding it structurally."""

    key: str
    label: str
    type: str
    required: bool = False
    options: list[str] = field(default_factory=list)
    item_fields: list["FormField"] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "FormField":
        return cls(
            key=data["key"],
            label=data.get("label", data["key"]),
            type=data.get("type", FIELD_TYPE_TEXT),
            required=bool(data.get("required", False)),
            options=list(data.get("options", [])),
            item_fields=[FormField.from_dict(f) for f in data.get("itemFields", [])],
        )


@dataclass
class DomainSchema:
    """A domain's full OP_GET_FIELD_SCHEMA response — enough for a generic card/form to render and
    edit records without any per-domain Python code. `title_field`/`title_fallback_field` pick the
    row's headline (falling back to the second if the first is blank); `subtitle_fields` are joined
    with " · " for the metadata line; `sort_field`/`sort_descending` order the list;
    `upcoming_only_field`, if set, hides records whose value for that field is in the past (this is
    calendar's "only show upcoming events" behavior, generalized as an opt-in rather than hardcoded
    calendar-specific logic)."""

    domain: str
    title_field: str
    fields: list[FormField]
    title_fallback_field: str | None = None
    subtitle_fields: list[str] = field(default_factory=list)
    sort_field: str | None = None
    sort_descending: bool = True
    upcoming_only_field: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "DomainSchema":
        return cls(
            domain=data["domain"],
            title_field=data["titleField"],
            title_fallback_field=data.get("titleFallbackField"),
            subtitle_fields=list(data.get("subtitleFields", [])),
            sort_field=data.get("sortField"),
            sort_descending=bool(data.get("sortDescending", True)),
            upcoming_only_field=data.get("upcomingOnlyField"),
            fields=[FormField.from_dict(f) for f in data.get("fields", [])],
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


# VoxResult.text for media_control when Commander's notification-listener permission isn't
# granted — see vox-commander's MediaControlIpcHandler.kt. This is a phone-side permission (Vox
# Commander, not VoxConnect itself), so the desktop can't request it directly; MediaCard just
# tells the user where to go on the phone — see MEDIA_PERMISSION_INSTRUCTIONS.
MEDIA_PERMISSION_NOT_GRANTED = "notification access not granted"
MEDIA_PERMISSION_INSTRUCTIONS = (
    "Media control needs notification access on your phone.\n"
    "On your phone: Settings → Apps → Special access → Notification access → "
    "enable Vox Commander."
)


def is_media_permission_missing(result: VoxResult) -> bool:
    return not result.ok and result.text == MEDIA_PERMISSION_NOT_GRANTED


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

    def to_dict(self) -> dict:
        """Mirror of from_dict, for pushing an edit back via sync_merge — see
        bridge/client.py's push_edit. Caller must bump updated_at before
        sending (sync_merge silently ignores a tie or older value)."""
        d = {
            "uid": self.uid,
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "location": self.location,
            "startMillis": self.start_millis,
            "endMillis": self.end_millis,
            "allDay": self.all_day,
            "completed": self.completed,
            "recurrenceFrequency": self.recurrence_frequency,
            "recurrenceUntilMillis": self.recurrence_until_millis,
            "layerName": self.layer_name,
            "tags": self.tags,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        return {k: v for k, v in d.items() if v is not None}


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

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "quantity": self.quantity,
            "unitPrice": self.unit_price,
            "position": self.position,
            "netAmount": self.net_amount,
            "vatAmount": self.vat_amount,
            "grossAmount": self.gross_amount,
        }
        return {k: v for k, v in d.items() if v is not None}


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

    def to_dict(self) -> dict:
        """Mirror of from_dict. lineItems is always included (even empty) —
        sync_merge replaces that list wholesale, not field-by-field, so
        omitting it would silently wipe existing items on the phone."""
        d = {
            "uid": self.uid,
            "title": self.title,
            "totalAmount": self.total_amount,
            "currencyCode": self.currency_code,
            "vendor": self.vendor,
            "bank": self.bank,
            "location": self.location,
            "dateTime": self.date_time,
            "comments": self.comments,
            "categoryName": self.category_name,
            "direction": self.direction,
            "receiptImageName": self.receipt_image_name,
            "isStub": self.is_stub,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        result = {k: v for k, v in d.items() if v is not None}
        result["lineItems"] = [item.to_dict() for item in self.line_items]
        return result


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

    def to_dict(self) -> dict:
        d = {
            "uid": self.uid,
            "title": self.title,
            "text": self.text,
            "categoryName": self.category_name,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class NowPlaying:
    """`albumArtBase64` (JPEG, pre-downscaled by MediaControlIpcHandler.kt) and
    `position`/`duration` are all optional — many sessions/apps don't populate one or more of
    them; absence isn't an error, just nothing to render for that part."""

    playing: bool
    package_name: str | None = None
    title: str | None = None
    artist: str | None = None
    album_art_base64: str | None = None
    position_millis: int | None = None
    duration_millis: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "NowPlaying":
        return cls(
            playing=bool(data.get("playing", False)),
            package_name=data.get("packageName"),
            title=data.get("title"),
            artist=data.get("artist"),
            album_art_base64=data.get("albumArtBase64"),
            position_millis=data.get("positionMillis"),
            duration_millis=data.get("durationMillis"),
        )
