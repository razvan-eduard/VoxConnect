"""HTTP client for the VoxConnect bridge (core/voxconnect in VoxApps, hosted
in Vox Hub).

Wire format, verified against the real Kotlin server (VoxConnectServer.kt):
- Every route requires header "Authorization: Bearer <deviceId>" — there is
  no unauthenticated route on this server at all; pairing happens out of
  band (see pairing/listener.py) via a push to a temporary local HTTP
  listener this app stands up itself, not via any route on the bridge.
- Every authenticated POST's request body, and every authenticated route's
  response body, is a single opaque string: crypto.encrypt/decrypt's
  base64(iv || ciphertext || tag) token. There is no JSON wrapper around it —
  the whole HTTP body *is* that token.
- GET requests carry no body (nothing to encrypt); their responses still are.
"""

from __future__ import annotations

import json
import time

import httpx

from voxconnect.bridge import crypto
from voxconnect.bridge.models import OP_GET_FIELD_SCHEMA, OP_SYNC_MERGE, AppInfo, DomainSchema, VoxCommand, VoxResult
from voxconnect.settings import PairedDevice

DEFAULT_TIMEOUT = 10.0


class BridgeError(Exception):
    """Raised for transport failures or a response that fails to decrypt."""


UNREACHABLE_MESSAGE = (
    "Can't reach your phone — check it's on the same WiFi network and unlocked. If this keeps "
    "happening, battery saver may be closing the bridge in the background: on your phone, go to "
    "Vox Hub's VoxConnect settings and allow background activity when prompted (or disable "
    "battery optimization for Vox Hub in your phone's battery settings)."
)


class BridgeClient:
    def __init__(self, device: PairedDevice, timeout: float = DEFAULT_TIMEOUT):
        self._device = device
        self._key = crypto.key_from_base64(device.key_base64)
        self._http = httpx.Client(base_url=device.base_url, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "BridgeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- authenticated routes ------------------------------------------------

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._device.device_id}"}

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Every real network failure (host unreachable, connection refused, timed out — e.g. a
        raw `OSError` like "[Errno 64] Host is down" or an `httpx.ConnectTimeout`) funnels through
        here so the UI only ever has to handle one friendly BridgeError, not a zoo of transport
        exception types with cryptic system-level text."""
        try:
            return self._http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise BridgeError(UNREACHABLE_MESSAGE) from exc

    def _decrypt_response(self, response: httpx.Response) -> str:
        if response.status_code != 200:
            raise BridgeError(f"request failed: {response.status_code} {response.text}")
        plaintext = crypto.decrypt(self._key, response.text)
        if plaintext is None:
            raise BridgeError("failed to decrypt response (bad key or tampered body)")
        return plaintext

    def get_apps(self) -> list[AppInfo]:
        response = self._request("GET", "/apps", headers=self._headers())
        plaintext = self._decrypt_response(response)
        return [AppInfo.from_dict(item) for item in json.loads(plaintext)]

    def get_field_schema(self, domain: str) -> DomainSchema:
        """Fetches the domain's editable-field description used to render a generic record card/
        form — see VoxFormSchema.kt (core/ipc) for the wire shape. Goes through the same generic
        `/command` route as every other op (VoxConnectServer.kt forwards any op to the domain's
        satellite verbatim); there is no dedicated schema route. Raises BridgeError (not a special
        "unsupported" return) if the satellite doesn't answer — an old APK that predates this op, or
        one that's simply uninstalled — callers doing multi-domain discovery should catch this per
        domain and skip that card rather than let one stale satellite break the whole dashboard."""
        result = self.send_command(VoxCommand(op=OP_GET_FIELD_SCHEMA, domain=domain))
        if not result.ok:
            raise BridgeError(result.text or f"no field schema for domain {domain!r}")
        return DomainSchema.from_dict(json.loads(result.text))

    def send_command(self, command: VoxCommand) -> VoxResult:
        token = crypto.encrypt(self._key, json.dumps(command.to_dict()))
        response = self._request("POST", "/command", content=token, headers=self._headers())
        plaintext = self._decrypt_response(response)
        return VoxResult.from_dict(json.loads(plaintext))

    @staticmethod
    def sync_merge_command(domain: str, entries: list[dict], tombstones: list[dict]) -> VoxCommand:
        """Builds (without sending) the sync_merge VoxCommand push_edit/delete_record send — a
        real per-uid upsert/tombstone (see core/datahygiene's SyncMerge.planMerge on the Android
        side), not a full-domain replace. Exposed as a staticmethod so callers that need to retry
        a failed write later (see bridge/outbox.py) can rebuild the exact same command without
        going through an instance method that immediately sends it."""
        body = json.dumps({"entries": entries, "tombstones": tombstones})
        return VoxCommand(op=OP_SYNC_MERGE, domain=domain, text=body)

    def push_edit(self, domain: str, entry: dict) -> VoxResult:
        """Pushes an edited (or brand new — sync_merge is upsert-by-uid, so a fresh uid is just
        as valid as an existing one) record back to the phone. `entry` must be the record's full
        current field set (dataclass.to_dict()) with `updatedAt` bumped strictly past the phone's
        stored value for an edit, or the edit is silently ignored as stale."""
        return self.send_command(self.sync_merge_command(domain, [entry], []))

    def delete_record(self, domain: str, uid: str) -> VoxResult:
        """Deletes a single record via sync_merge's tombstone side — the delete counterpart of
        push_edit, same real per-uid mutation, not a soft/local-only removal."""
        tombstone = {"uid": uid, "deletedAt": int(time.time() * 1000)}
        return self.send_command(self.sync_merge_command(domain, [], [tombstone]))

    def get_media(self) -> VoxResult:
        response = self._request("GET", "/media", headers=self._headers())
        plaintext = self._decrypt_response(response)
        return VoxResult.from_dict(json.loads(plaintext))

    def media_action(self, action: str) -> VoxResult:
        response = self._request("POST", f"/media/{action}", headers=self._headers())
        plaintext = self._decrypt_response(response)
        return VoxResult.from_dict(json.loads(plaintext))

    def query(self, text: str) -> VoxResult:
        """Reserved endpoint — the real bridge always returns
        {ok: false, text: "not yet implemented"} today. Do not build real
        LLM plumbing around this; it's a UI-only stub for now."""
        token = crypto.encrypt(self._key, json.dumps({"text": text}))
        response = self._request("POST", "/query", content=token, headers=self._headers())
        plaintext = self._decrypt_response(response)
        return VoxResult.from_dict(json.loads(plaintext))
