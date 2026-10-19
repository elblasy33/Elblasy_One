"""Explicit compatibility matrix. A series is supported only once its integration tests pass."""

from dataclasses import dataclass
from typing import Any

SUPPORTED_SERIES = {"18.0", "19.0"}  # verified by tests/integration on real instances
SUPPORTED_CONTRACT_VERSIONS = {1}
# Product target is Odoo Community. Enterprise is never a dependency and is not verified.
SUPPORTED_EDITIONS = {"community"}


@dataclass(frozen=True)
class Compatibility:
    status: str  # supported | unverified_edition | unsupported_version | unsupported_contract
    reason: str


def assess(manifest: dict[str, Any]) -> Compatibility:
    series = manifest.get("odoo", {}).get("series")
    if series not in SUPPORTED_SERIES:
        return Compatibility("unsupported_version", f"Odoo {series} has not been verified")
    edition = manifest.get("odoo", {}).get("edition")
    if edition not in SUPPORTED_EDITIONS:
        return Compatibility("unverified_edition", f"{edition} edition is not a verified target")
    if manifest.get("contract_version") not in SUPPORTED_CONTRACT_VERSIONS:
        return Compatibility("unsupported_contract", "bridge contract version not supported")
    return Compatibility("supported", f"Odoo {series} verified")
