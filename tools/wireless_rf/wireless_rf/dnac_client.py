"""Small read/download Catalyst Center API clients."""

from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class CatalystCenterTransport:
    """Shared Catalyst Center auth and HTTP transport."""

    base_url: str
    username: str
    password: str
    verify_tls: bool = True
    timeout_seconds: int = 60
    token: str | None = None

    def __post_init__(self) -> None:
        """Normalize connection options after dataclass initialization."""

        self.base_url = self.base_url.rstrip("/")
        self._context = None if self.verify_tls else ssl._create_unverified_context()

    def authenticate(self) -> str:
        """Authenticate with basic auth and cache the returned API token."""

        auth_bytes = f"{self.username}:{self.password}".encode("utf-8")
        headers = {
            "Authorization": "Basic " + base64.b64encode(auth_bytes).decode("ascii"),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = self._request_json("POST", "/dna/system/api/v1/auth/token", headers=headers)
        token = payload.get("Token") or payload.get("token")
        if not token:
            raise RuntimeError(f"Catalyst Center auth response did not include a token: {payload}")
        self.token = str(token)
        return self.token

    def _headers(self, accept: str = "application/json", content_type: str | None = "application/json") -> dict[str, str]:
        """Return headers with a valid Catalyst Center auth token."""

        if not self.token:
            self.authenticate()
        headers = {
            "X-Auth-Token": self.token or "",
            "Accept": accept,
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Send one JSON request and convert HTTP/API failures to RuntimeError."""

        url = self.base_url + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers or self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds, context=self._context) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Catalyst Center HTTP {exc.code} for {method} {path}: {detail}") from exc
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return raw.decode("utf-8", errors="replace")

    def _request_bytes(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        """Send one request and return the raw response body."""

        url = self.base_url + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers or self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds, context=self._context) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Catalyst Center HTTP {exc.code} for {method} {path}: {detail}") from exc


class CatalystCenterIcapReadClient:
    """Read/download-only client for Study Web ICAP workflows."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        verify_tls: bool = True,
        timeout_seconds: int = 60,
    ) -> None:
        """Create an ICAP read client with its own private transport."""

        self._transport = CatalystCenterTransport(
            base_url=base_url,
            username=username,
            password=password,
            verify_tls=verify_tls,
            timeout_seconds=timeout_seconds,
        )

    def get_client_detail(self, mac_address: str, timestamp_ms: int | None = None) -> dict[str, Any]:
        """Fetch Catalyst Center client-detail JSON for a client MAC."""

        params = {"macAddress": mac_address}
        if timestamp_ms is not None:
            params["timestamp"] = str(timestamp_ms)
        query = urllib.parse.urlencode(params)
        payload = self._transport._request_json("GET", f"/dna/intent/api/v1/client-detail?{query}")
        if not isinstance(payload, dict):
            return {"response": payload}
        return payload

    def list_icap_capture_files(
        self,
        capture_type: str,
        *,
        client_mac: str | None = None,
        ap_mac: str | None = None,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int | None = None,
        offset: int | None = None,
        sort_by: str | None = None,
        order: str | None = None,
    ) -> dict[str, Any]:
        """List ICAP packet capture files matching Catalyst Center filters."""

        params: dict[str, str | int] = {"type": capture_type}
        if client_mac:
            params["clientMac"] = client_mac
        if ap_mac:
            params["apMac"] = ap_mac
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if sort_by:
            params["sortBy"] = sort_by
        if order:
            params["order"] = order
        query = urllib.parse.urlencode(params)
        payload = self._transport._request_json("GET", f"/dna/data/api/v1/icap/captureFiles?{query}")
        if not isinstance(payload, dict):
            return {"response": payload}
        return payload

    def download_icap_capture_file(self, capture_file_id: str) -> bytes:
        """Download one ICAP packet capture file as raw bytes."""

        encoded_id = urllib.parse.quote(capture_file_id, safe="")
        return self._transport._request_bytes(
            "GET",
            f"/dna/data/api/v1/icap/captureFiles/{encoded_id}/download",
            headers=self._transport._headers(accept="application/octet-stream", content_type=None),
        )


class CatalystCenterTopologyReadClient:
    """Read-only client for Catalyst Center topology/inventory workflows."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        verify_tls: bool = True,
        timeout_seconds: int = 60,
    ) -> None:
        """Create a topology read client with its own private transport."""

        self._transport = CatalystCenterTransport(
            base_url=base_url,
            username=username,
            password=password,
            verify_tls=verify_tls,
            timeout_seconds=timeout_seconds,
        )

    @property
    def base_url(self) -> str:
        """Return the configured Catalyst Center base URL for drilldown links."""

        return self._transport.base_url

    def list_network_devices(self, page_limit: int = 500) -> list[dict[str, Any]]:
        """Fetch Catalyst Center network-device inventory."""

        def response_payload(payload: Any) -> Any:
            if isinstance(payload, dict) and "response" in payload:
                return payload["response"]
            return payload

        def response_list(payload: Any) -> list[dict[str, Any]]:
            response = response_payload(payload)
            if not isinstance(response, list):
                return []
            return [dict(item) for item in response if isinstance(item, dict)]

        try:
            count_payload = self._transport._request_json("GET", "/dna/intent/api/v1/network-device/count")
            count = int(response_payload(count_payload))
        except Exception:
            count = 0

        if count <= 0:
            return response_list(self._transport._request_json("GET", "/dna/intent/api/v1/network-device"))

        devices: list[dict[str, Any]] = []
        offset = 1
        while len(devices) < count:
            query = urllib.parse.urlencode({"limit": page_limit, "offset": offset})
            page = response_list(self._transport._request_json("GET", f"/dna/intent/api/v1/network-device?{query}"))
            if not page:
                break
            devices.extend(page)
            if len(page) < page_limit:
                break
            offset += page_limit
        return devices

    def get_site_topology(self) -> dict[str, Any]:
        """Fetch Catalyst Center site topology."""

        payload = self._transport._request_json("GET", "/dna/intent/api/v1/topology/site-topology")
        if not isinstance(payload, dict):
            return {"response": payload}
        return payload

    def get_physical_topology(self) -> dict[str, Any]:
        """Fetch Catalyst Center physical topology."""

        payload = self._transport._request_json("GET", "/dna/intent/api/v1/topology/physical-topology")
        if not isinstance(payload, dict):
            return {"response": payload}
        return payload
