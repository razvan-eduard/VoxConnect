# VoxConnect

A portable, cross-platform (Windows/macOS/Linux) desktop companion for the Android app
**Vox Commander**. VoxConnect pairs with a phone over the local WiFi network to:

- Send commands to the phone: create expenses, notes, and calendar events.
- Display live widgets (upcoming events, recent expenses, recent notes) — the phone is the
  database; VoxConnect keeps only an in-memory/session cache, never a persistent local copy
  of domain data.
- Mirror selected phone notifications as a live feed.
- Control phone media playback (play/pause/next/previous, now-playing info).
- Respect the phone's existing lock state: if the relevant app is biometric-locked,
  VoxConnect shows "phone locked" for the affected widget instead of prompting for its own
  credential.

## Status

Early scaffold — see the project's task tracker for progress. Pairs with the VoxConnect
bridge shipped in [VoxApps](https://github.com/razvan-eduard/VoxApps)' Vox Hub app
(`core/voxconnect`).

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,mock]"
python -m voxconnect.app
```

## License

GPLv3 — see [LICENSE](LICENSE).
