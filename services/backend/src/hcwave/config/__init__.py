"""Configuration entry point.

Usage::

    from hcwave.config import get_settings

    settings = get_settings()
    hospital = settings.hospitals["demo-hospital"]

The config directory is ``$HCWAVE_CONFIG_DIR`` (``/app/config`` in the
container) or the nearest ``config/`` folder above the working directory.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from hcwave.config.loader import (
    ConfigError,
    deep_merge,
    interpolate_env,
    load_layered_config,
    read_yaml,
    read_yaml_dir,
)
from hcwave.config.schema import HospitalConfig, Settings

__all__ = ["ConfigError", "Settings", "get_settings", "find_config_dir", "load_settings"]


def find_config_dir() -> Path:
    """Locates the configuration directory.

    Returns:
        ``$HCWAVE_CONFIG_DIR`` if set, otherwise the first ``config/`` folder
        containing ``app.yaml`` found walking up from the working directory.

    Raises:
        ConfigError: If no configuration directory can be found.
    """
    explicit = os.environ.get("HCWAVE_CONFIG_DIR")
    if explicit:
        return Path(explicit)
    for folder in [Path.cwd(), *Path.cwd().parents]:
        candidate = folder / "config"
        if (candidate / "app.yaml").is_file():
            return candidate
    raise ConfigError("Cannot find config/app.yaml; set HCWAVE_CONFIG_DIR")


def _load_named_files(directory: Path) -> dict[str, dict[str, Any]]:
    """Reads ``<name>.yaml`` files into a mapping keyed by file stem."""
    if not directory.is_dir():
        return {}
    return {
        path.stem: read_yaml(path)
        for path in sorted(directory.iterdir())
        if path.suffix in {".yaml", ".yml"}
    }


def load_settings(
    config_dir: Path | None = None,
    environment: str | None = None,
    overlay_dir: Path | None = None,
) -> Settings:
    """Builds a validated :class:`Settings` from all configuration files.

    Args:
        config_dir: Config directory; discovered automatically when omitted.
        environment: Environment overlay to apply; defaults to ``$APP_ENV``.
        overlay_dir: Deployment overlay directory; defaults to
            ``$HCWAVE_CONFIG_OVERLAY_DIR``.

    Returns:
        The validated settings object.
    """
    # A local .env file is optional; real deployments inject env vars directly.
    load_dotenv(os.environ.get("HCWAVE_ENV_FILE", ".env"), override=False)

    config_dir = config_dir or find_config_dir()
    environment = environment or os.environ.get("APP_ENV", "dev")
    if overlay_dir is None and os.environ.get("HCWAVE_CONFIG_OVERLAY_DIR"):
        overlay_dir = Path(os.environ["HCWAVE_CONFIG_OVERLAY_DIR"])

    data = load_layered_config(config_dir, environment, overlay_dir)

    # Tenants: one file per hospital, plus inline overrides from overlays.
    hospitals: dict[str, Any] = {}
    for raw in read_yaml_dir(config_dir / "hospitals"):
        hospital = interpolate_env(raw)
        hospitals[hospital["id"]] = hospital
    for hospital_id, raw in (data.pop("hospitals", None) or {}).items():
        hospitals[hospital_id] = deep_merge(hospitals.get(hospital_id, {}), raw)

    templates_file = config_dir / "messaging" / "templates.yaml"
    templates = read_yaml(templates_file).get("templates", {}) if templates_file.is_file() else {}
    templates = deep_merge(templates, data.pop("templates", None) or {})

    locales = deep_merge(_load_named_files(config_dir / "locales"), data.pop("locales", None) or {})
    prompts = deep_merge(_load_named_files(config_dir / "prompts"), data.pop("prompts", None) or {})

    return Settings.model_validate(
        {
            **data,
            "hospitals": {k: v for k, v in hospitals.items() if v.get("active", True)},
            "templates": templates,
            "locales": locales,
            "prompts": prompts,
        }
    )


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Returns the process-wide settings, loading them on first use."""
    return load_settings()


def hospital_for_channel(settings: Settings, channel_id: str) -> HospitalConfig | None:
    """Finds the hospital that owns a messaging channel identifier.

    Args:
        settings: Loaded settings.
        channel_id: Channel registration ID / phone number ID from the event.

    Returns:
        The owning hospital, or the only configured hospital when exactly one
        exists and the channel is unknown (single-tenant pilots), else None.
    """
    for hospital in settings.hospitals.values():
        if channel_id in hospital.channel_ids:
            return hospital
    if len(settings.hospitals) == 1:
        return next(iter(settings.hospitals.values()))
    return None
