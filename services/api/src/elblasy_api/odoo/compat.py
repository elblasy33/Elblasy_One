"""Explicit compatibility matrix. A series is supported only once its integration tests pass."""

from dataclasses import dataclass
from typing import Any

SUPPORTED_SERIES = {"18.0", "19.0"}  # verified by tests/integration on real instances
SUPPORTED_CONTRACT_VERSIONS = {1}


@dataclass(frozen=True)
class Compatibility:
    status: str  # supported | unsupported_version | unsupported_contract
    reason: str


def assess(manifest: dict[str, Any]) -> Compatibility:
    series = manifest.get("odoo", {}).get("series")
    if series not in SUPPORTED_SERIES:
        return Compatibility("unsupported_version", f"Odoo {series} has not been verified")
    if manifest.get("contract_version") not in SUPPORTED_CONTRACT_VERSIONS:
        return Compatibility("unsupported_contract", "bridge contract version not supported")
    return Compatibility("supported", f"Odoo {series} verified")
