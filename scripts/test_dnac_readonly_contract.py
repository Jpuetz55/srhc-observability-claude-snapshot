#!/usr/bin/env python3
"""Permanent Catalyst Center read/download boundary tests."""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
sys.path.insert(0, str(ROOT / "tools" / "wireless_rf"))

import wireless_rf.dnac_client as dnac_client  # noqa: E402
from wireless_rf.dnac_client import CatalystCenterIcapReadClient  # noqa: E402
from wireless_rf.dnac_client import CatalystCenterTopologyReadClient  # noqa: E402
from wireless_rf.dnac_client import CatalystCenterTransport  # noqa: E402


ACTIVE_SOURCE_ROOTS = (
    ROOT / "tools",
    ROOT / "scripts",
    ROOT / "config",
    ROOT / "systemd",
    ROOT / "web",
    ROOT / "systemd-overrides",
    ROOT / "deploy",
    ROOT / "topology",
)
ACTIVE_SOURCE_FILES = (ROOT / "Makefile",)
CLIENT_SOURCE = ROOT / "tools" / "wireless_rf" / "wireless_rf" / "dnac_client.py"
SKIP_PARTS = {
    "__pycache__",
    "node_modules",
    "dist",
    "static",
    ".git",
}
TEXT_SUFFIXES = {
    ".py",
    ".sh",
    ".yaml",
    ".yml",
    ".service",
    ".timer",
    ".conf",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
}
FORBIDDEN_PATTERNS = (
    "/network-device-poller/cli/read-request",
    "run_commands(",
    "submit_cli_read_request(",
    "deploy_icap_settings(",
    "/icapSettings/deploy",
    "collect-dnac",
    "collect-ipad-client-detail",
    "catalyst_center_wlc_ping",
)
APPROVED_ICAP_PATH_PREFIXES = (
    "/dna/system/api/v1/auth/token",
    "/dna/intent/api/v1/client-detail?",
    "/dna/data/api/v1/icap/captureFiles?",
    "/dna/data/api/v1/icap/captureFiles/",
)
APPROVED_TRANSPORT_PATH_PREFIXES = (
    "/dna/system/api/v1/auth/token",
)
APPROVED_TOPOLOGY_PATH_PREFIXES = (
    "/dna/intent/api/v1/network-device/count",
    "/dna/intent/api/v1/network-device?",
    "/dna/intent/api/v1/network-device",
    "/dna/intent/api/v1/topology/site-topology",
    "/dna/intent/api/v1/topology/physical-topology",
)
APPROVED_ICAP_PUBLIC_METHODS = {
    "get_client_detail",
    "list_icap_capture_files",
    "download_icap_capture_file",
}
APPROVED_TOPOLOGY_PUBLIC_METHODS = {
    "list_network_devices",
    "get_site_topology",
    "get_physical_topology",
}
PRIVATE_TRANSPORT_CALLS = (
    "._request(",
    "._request_json(",
    "._request_bytes(",
    "._headers(",
)
DNAC_READONLY_ENV_FILE = "/etc/grafana-mimir-observability/secrets/dnac-readonly.env"


def require(condition: bool, message: str) -> None:
    """Raise AssertionError with a concise contract-test failure message."""

    if not condition:
        raise AssertionError(message)


def iter_active_source_files() -> list[Path]:
    """Return active source/config files, excluding generated frontend assets."""

    files: list[Path] = []
    for root in ACTIVE_SOURCE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path == SELF or any(part in SKIP_PARTS for part in path.parts):
                continue
            if path.is_file() and path.suffix in TEXT_SUFFIXES:
                files.append(path)
    files.extend(path for path in ACTIVE_SOURCE_FILES if path.exists())
    return sorted(files)


def test_forbidden_capabilities_absent() -> None:
    """Fail if an active source path reintroduces device commands or ICAP writes."""

    violations: list[str] = []
    for path in iter_active_source_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in FORBIDDEN_PATTERNS:
            if pattern in text:
                violations.append(f"{path.relative_to(ROOT)} contains {pattern!r}")
    require(not violations, "Forbidden Catalyst Center capability found:\n" + "\n".join(violations))


def _string_literals(source: str) -> list[str]:
    """Extract string literals and f-string literal prefixes from Python source."""

    tree = ast.parse(source)
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            parts = [
                value.value
                for value in node.values
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            ]
            if parts:
                literals.append("".join(parts))
    return literals


def _public_methods(cls: type) -> set[str]:
    """Return public function names directly exposed by a client class."""

    return {
        name
        for name, value in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


def _path_literals_for_class(cls: type) -> list[str]:
    """Return Catalyst Center API path literals from one class source."""

    return [
        value
        for value in _string_literals(inspect.getsource(cls))
        if value.startswith("/dna/")
    ]


def _assert_paths_allowed(class_name: str, paths: list[str], allowed_prefixes: tuple[str, ...]) -> None:
    """Fail when a class source contains a path outside its allowlist."""

    disallowed = [
        value
        for value in paths
        if not any(value.startswith(prefix) for prefix in allowed_prefixes)
    ]
    require(not disallowed, f"Disallowed {class_name} path literals: {disallowed}")


def test_narrow_client_allowlists() -> None:
    """Verify each Catalyst Center client exposes only approved read/download methods."""

    require(
        not hasattr(dnac_client, "CatalystCenterClient"),
        "Generic CatalystCenterClient alias must not exist",
    )

    public_methods = _public_methods(CatalystCenterIcapReadClient)
    require(
        public_methods == APPROVED_ICAP_PUBLIC_METHODS,
        f"Unexpected CatalystCenterIcapReadClient methods: {sorted(public_methods)}",
    )
    _assert_paths_allowed(
        "ICAP client",
        _path_literals_for_class(CatalystCenterIcapReadClient),
        APPROVED_ICAP_PATH_PREFIXES,
    )

    public_topology_methods = _public_methods(CatalystCenterTopologyReadClient)
    require(
        public_topology_methods == APPROVED_TOPOLOGY_PUBLIC_METHODS,
        f"Unexpected CatalystCenterTopologyReadClient methods: {sorted(public_topology_methods)}",
    )
    _assert_paths_allowed(
        "topology client",
        _path_literals_for_class(CatalystCenterTopologyReadClient),
        APPROVED_TOPOLOGY_PATH_PREFIXES,
    )

    transport_paths = _path_literals_for_class(CatalystCenterTransport)
    _assert_paths_allowed("transport", transport_paths, APPROVED_TRANSPORT_PATH_PREFIXES)


def test_private_transport_not_called_outside_client() -> None:
    """Fail if active code calls private Catalyst Center transport helpers."""

    violations: list[str] = []
    for path in iter_active_source_files():
        if path == CLIENT_SOURCE:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in PRIVATE_TRANSPORT_CALLS:
            if needle in text:
                violations.append(f"{path.relative_to(ROOT)} calls {needle}")
    require(not violations, "Private Catalyst Center transport use found:\n" + "\n".join(violations))


class _PostCallVisitor(ast.NodeVisitor):
    """Collect Catalyst Center request calls that use POST outside authentication."""

    def __init__(self) -> None:
        self.function_stack: list[str] = []
        self.violations: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        method = self._request_method_literal(node)
        if method == "POST" and (not self.function_stack or self.function_stack[-1] != "authenticate"):
            line = getattr(node, "lineno", "?")
            function_name = self.function_stack[-1] if self.function_stack else "<module>"
            self.violations.append(f"{function_name} line {line}")
        self.generic_visit(node)

    @staticmethod
    def _request_method_literal(node: ast.Call) -> str | None:
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"_request_json", "_request_bytes"}:
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                return node.args[0].value.upper()
            for keyword in node.keywords:
                if keyword.arg == "method" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    return keyword.value.value.upper()
        return None


def test_no_client_post_except_authentication() -> None:
    """Verify client methods never issue state-changing POST requests."""

    tree = ast.parse(CLIENT_SOURCE.read_text(encoding="utf-8"))
    visitor = _PostCallVisitor()
    visitor.visit(tree)
    require(
        not visitor.violations,
        "Catalyst Center client POST outside authenticate(): " + ", ".join(visitor.violations),
    )


def test_dnac_defaults_use_readonly_secret() -> None:
    """Verify active ICAP/topology defaults use the shared DNAC read-only secret."""

    expected_refs = {
        "Makefile": ROOT / "Makefile",
        "Study Web unit": ROOT / "systemd" / "vocera-rf-validation-study-web.service",
        "Study Web app": ROOT / "tools" / "study_web" / "main.py",
        "ICAP helper": ROOT / "tools" / "vocera_media_qoe" / "vocera_dnac_icap.py",
        "topology publisher": ROOT / "scripts" / "publish_dnac_topology.py",
        "survey refresh": ROOT / "scripts" / "run_vocera_survey_refresh.sh",
    }
    missing = [
        label
        for label, path in expected_refs.items()
        if DNAC_READONLY_ENV_FILE not in path.read_text(encoding="utf-8", errors="replace")
    ]
    require(not missing, "DNAC defaults do not use the read-only secret: " + ", ".join(missing))

    installer_text = (ROOT / "scripts" / "install_vocera_media_qoe_textfile.sh").read_text(encoding="utf-8")
    for key in ("DNAC_BASE_URL=", "DNAC_USERNAME=", "DNAC_PASSWORD=", "DNAC_VERIFY_TLS="):
        require(key not in installer_text, f"media textfile installer must not create {key} in parser env")


def main() -> int:
    """Run the Catalyst Center read/download security contract."""

    test_forbidden_capabilities_absent()
    test_narrow_client_allowlists()
    test_private_transport_not_called_outside_client()
    test_no_client_post_except_authentication()
    test_dnac_defaults_use_readonly_secret()
    print("OK: Catalyst Center read/download contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
