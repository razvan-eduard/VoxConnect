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

import httpx

from voxconnect.bridge import crypto
from voxconnect.bridge.models import AppInfo, VoxCommand, VoxResult
from voxconnect.settings import PairedDevice

DEFAULT_TIMEOUT = 10.0


class BridgeError(Exception):
    """Raised for transport failures or a response that fails to decrypt."""


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

    def _decrypt_response(self, response: httpx.Response) -> str:
        if response.status_code != 200:
            raise BridgeError(f"request failed: {response.status_code} {response.text}")
        plaintext = crypto.decrypt(self._key, response.text)
        if plaintext is None:
            raise BridgeError("failed to decrypt response (bad key or tampered body)")
        return plaintext

    def get_apps(self) -> list[AppInfo]:
        response = self._http.get("/apps", headers=self._headers())
        plaintext = self._decrypt_response(response)
        return [AppInfo.from_dict(item) for item in json.loads(plaintext)]

    def send_command(self, command: VoxCommand) -> VoxResult:
        token = crypto.encrypt(self._key, json.dumps(command.to_dict()))
        response = self._http.post("/command", content=token, headers=self._headers())
        plaintext = self._decrypt_response(response)
        return VoxResult.from_dict(json.loads(plaintext))

    def get_media(self) -> VoxResult:
        response = self._http.get("/media", headers=self._headers())
        plaintext = self._decrypt_response(response)
        return VoxResult.from_dict(json.loads(plaintext))

    def media_action(self, action: str) -> VoxResult:
        response = self._http.post(f"/media/{action}", headers=self._headers())
        plaintext = self._decrypt_response(response)
        return VoxResult.from_dict(json.loads(plaintext))

    def query(self, text: str) -> VoxResult:
        """Reserved endpoint — the real bridge always returns
        {ok: false, text: "not yet implemented"} today. Do not build real
        LLM plumbing around this; it's a UI-only stub for now."""
        token = crypto.encrypt(self._key, json.dumps({"text": text}))
        response = self._http.post("/query", content=token, headers=self._headers())
        plaintext = self._decrypt_response(response)
        return VoxResult.from_dict(json.loads(plaintext))
