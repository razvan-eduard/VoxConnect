"""Local-first parsing for the Ask bar's `>`-prefixed shorthand syntax (e.g. `> exp 47 emag`)
and a local fuzzy filter over every domain already cached on the desktop — both driven entirely
by whatever DomainSchema set the phone actually advertised this session, not a hardcoded
expenses/notes pair. A newly discovered domain gets shorthand + search support automatically.

Important honesty note about the command shorthand: `create` on the Android side has no
structured wire fields (no amount/vendor on VoxCommand) — every `create` is natural-language text
that the phone parses via an LLM, and none of it replies with a confirmation (it's fire-and-forget,
same as voice commands). So `parse_command` doesn't build a "fast, structured, instant" record —
it just reconstructs the shorthand into the natural-language sentence the phone's existing create
pipeline already expects, saving typing, not round-trip time. Callers must not present this as
instant/confirmed creation; see ParsedCommand.description's wording.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from voxconnect.bridge.models import OP_CREATE, DomainSchema, VoxCommand
from voxconnect.cache.store import CacheStore

COMMAND_PREFIX = ">"

# A leading bare number written with a comma decimal (e.g. "47,50 emag") is normalized to a dot
# regardless of which domain the command targets — not expense-specific, since any domain could
# have a numeric field a user wants to type quickly using their locale's decimal separator.
_LEADING_COMMA_DECIMAL = re.compile(r"^(\d+),(\d+)(.*)$", re.DOTALL)


@dataclass
class ParsedCommand:
    command: VoxCommand
    description: str


def _normalize_leading_decimal(text: str) -> str:
    match = _LEADING_COMMA_DECIMAL.match(text)
    return f"{match.group(1)}.{match.group(2)}{match.group(3)}" if match else text


def _match_domain(keyword: str, schemas: dict[str, DomainSchema]) -> str | None:
    """Exact domain match, or an unambiguous prefix match (e.g. "exp" -> "expenses", "note"/
    "notes" -> "notes") — a keyword prefixing more than one discovered domain is treated as
    unrecognized rather than guessed."""
    if keyword in schemas:
        return keyword
    candidates = [domain for domain in schemas if domain.startswith(keyword)]
    return candidates[0] if len(candidates) == 1 else None


def parse_command(text: str, schemas: dict[str, DomainSchema]) -> ParsedCommand | None:
    """`> <domain-prefix> <text...>` — returns None if `text` doesn't start with COMMAND_PREFIX,
    has no second word, or its first word doesn't unambiguously match a currently-discovered
    domain; the caller falls back to fuzzy record search / the free-form /query op."""
    if not text.startswith(COMMAND_PREFIX):
        return None
    body = text[len(COMMAND_PREFIX):].strip()
    if not body:
        return None

    parts = body.split(None, 1)
    if len(parts) != 2:
        return None
    keyword, rest = parts[0].lower(), _normalize_leading_decimal(parts[1].strip())
    if not rest:
        return None

    domain = _match_domain(keyword, schemas)
    if domain is None:
        return None
    command = VoxCommand(op=OP_CREATE, domain=domain, text=rest)
    return ParsedCommand(command, f"New {domain} record (phone will parse): {rest}")


def fuzzy_search_records(
    cache: CacheStore, schemas: dict[str, DomainSchema], query: str, limit: int = 5
) -> list[tuple[str, dict]]:
    """Pure substring match over every discovered domain's already-cached records (title,
    fallback title, and subtitle field values — the same fields a card actually shows),
    case-insensitive, no network, instant. Domain-agnostic by construction: a newly discovered
    domain becomes searchable automatically since it's driven by schemas, not a hardcoded field
    list. Not a real fuzzy/ranked search algorithm; good enough for "did I already write this
    down" at typing speed, which is all this is for. Returns (domain, record) pairs, capped at
    `limit` total across all domains combined."""
    query_lower = query.lower()
    matches: list[tuple[str, dict]] = []
    for domain in sorted(schemas):
        schema = schemas[domain]
        for record in cache.get_entries(domain):
            if query_lower in _searchable_text(schema, record):
                matches.append((domain, record))
                if len(matches) >= limit:
                    return matches
    return matches


def _searchable_text(schema: DomainSchema, record: dict) -> str:
    parts = [str(record.get(schema.title_field) or "")]
    if schema.title_fallback_field:
        parts.append(str(record.get(schema.title_fallback_field) or ""))
    for key in schema.subtitle_fields:
        value = record.get(key)
        if not value:
            continue
        parts.append(", ".join(str(v) for v in value) if isinstance(value, list) else str(value))
    return " ".join(parts).lower()
