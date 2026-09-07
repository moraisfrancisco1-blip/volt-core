from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class ExternalConnectorConfig:
    # Generic, reusable shape for any read-only external system Volt Core connects to
    # (VoltarisOS today, the Dai Oakes admin panel later) -- nothing here is specific to
    # any one product. `name` is only used in error messages; the real access boundary is
    # whatever the remote service's own API key actually authorizes.
    #
    # api_key_header/api_key_scheme are configurable because not every service uses the
    # same convention: VoltarisOS's real API expects a raw value in a custom header
    # (X-Volt-Core-Key), NOT "Authorization: Bearer <value>" -- confirmed live 2026-09-07
    # (Bearer returns 401 "Token inválido ou expirado", the custom header returns 200).
    # Default stays Authorization/Bearer since that's the more common convention for
    # whatever the next integration turns out to be.
    name: str
    base_url: str
    api_key_env_var: str
    api_key_header: str = "Authorization"
    api_key_scheme: str | None = "Bearer"


def get(config: ExternalConnectorConfig, path: str, *, params: dict | None = None, timeout: float = 15) -> dict:
    # The single seam tests substitute -- never touches the network once monkeypatched.
    # GET only, by construction: this function has no method parameter, so nothing built
    # on top of it can accidentally (or be prompted into) issuing a write.
    api_key = os.getenv(config.api_key_env_var)
    if not api_key:
        return {"error": f"{config.api_key_env_var} not configured"}
    if not config.base_url:
        return {"error": f"{config.name} base URL not configured"}
    header_value = f"{config.api_key_scheme} {api_key}" if config.api_key_scheme else api_key
    headers = {config.api_key_header: header_value}
    try:
        with httpx.Client(base_url=config.base_url, timeout=timeout) as client:
            response = client.get(path, headers=headers, params=params)
    except httpx.HTTPError:
        return {"error": f"{config.name} API request failed (network/transport error)"}
    if response.status_code != 200:
        return {"error": f"{config.name} API returned {response.status_code}"}
    try:
        return {"data": response.json()}
    except ValueError:
        return {"error": f"{config.name} API returned a non-JSON response"}
