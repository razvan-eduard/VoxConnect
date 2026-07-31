"""Local settings persistence: paired-device info and widget layout only.

No domain data (events/expenses/notes) is ever cached here — the phone is the
only source of truth, per the VoxConnect kickoff spec. This file just
remembers who we're paired with and where the dashboard's cards are.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from platformdirs import user_config_dir

APP_NAME = "VoxConnect"
APP_AUTHOR = "razvan-eduard"


def config_dir() -> Path:
    path = Path(user_config_dir(APP_NAME, APP_AUTHOR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _settings_path() -> Path:
    return config_dir() / "settings.json"


@dataclass
class PairedDevice:
    device_id: str
    key_base64: str
    host: str
    port: int
    label: str

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def load_paired_device() -> PairedDevice | None:
    path = _settings_path()
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    device = data.get("paired_device")
    if not device:
        return None
    return PairedDevice(**device)


def save_paired_device(device: PairedDevice) -> None:
    path = _settings_path()
    data = json.loads(path.read_text()) if path.exists() else {}
    data["paired_device"] = asdict(device)
    path.write_text(json.dumps(data, indent=2))


def clear_paired_device() -> None:
    path = _settings_path()
    if not path.exists():
        return
    data = json.loads(path.read_text())
    data.pop("paired_device", None)
    path.write_text(json.dumps(data, indent=2))
