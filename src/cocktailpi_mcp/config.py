from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    base_url: str
    access_token: str | None
    username: str | None
    password: str | None
    timeout_seconds: float



def load_settings() -> Settings:
    base_url = os.getenv("COCKTAILPI_BASE_URL", "http://localhost:8080").strip()
    access_token = os.getenv("COCKTAILPI_ACCESS_TOKEN", "").strip() or None
    username = os.getenv("COCKTAILPI_USERNAME", "").strip() or None
    password = os.getenv("COCKTAILPI_PASSWORD", "").strip() or None

    timeout_raw = os.getenv("COCKTAILPI_TIMEOUT_SECONDS", "20").strip()
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError as exc:
        raise ValueError("COCKTAILPI_TIMEOUT_SECONDS must be numeric") from exc

    return Settings(
        base_url=base_url.rstrip("/"),
        access_token=access_token,
        username=username,
        password=password,
        timeout_seconds=timeout_seconds,
    )
