"""Layered YAML configuration loader.

Configuration is resolved in this order, later layers winning:

1. ``<config_dir>/app.yaml`` – base defaults shared by every environment.
2. ``<config_dir>/environments/<APP_ENV>.yaml`` – environment overlay.
3. Every ``*.yaml`` file in ``$HCWAVE_CONFIG_OVERLAY_DIR`` – deployment overlay
   (mounted from a Kubernetes ConfigMap by the Helm chart).

String values may reference environment variables with ``${VAR}`` or
``${VAR:-default}``. Secrets therefore never live in YAML: they come from the
process environment, which is populated from a local ``.env`` file during
development and from Azure Key Vault (via the Secrets Store CSI driver) in AKS.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

# ${VAR} or ${VAR:-default}. The default may itself be empty.
_ENV_PATTERN = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}")


class ConfigError(RuntimeError):
    """Raised when configuration files are missing or invalid."""


def interpolate_env(value: Any, environ: Mapping[str, str] | None = None) -> Any:
    """Recursively replaces ``${VAR}`` placeholders with environment values.

    Args:
        value: A scalar, list or mapping loaded from YAML.
        environ: Environment to read from. Defaults to ``os.environ``.

    Returns:
        The same structure with every placeholder substituted. Unset variables
        without a default resolve to an empty string so optional secrets can be
        left blank; adapters validate the settings they actually need.
    """
    env = os.environ if environ is None else environ
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: env.get(m.group("name"), m.group("default") or ""), value)
    if isinstance(value, list):
        return [interpolate_env(item, env) for item in value]
    if isinstance(value, dict):
        return {key: interpolate_env(item, env) for key, item in value.items()}
    return value


def deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Merges ``overlay`` into a copy of ``base``.

    Nested mappings are merged key by key; any other value in ``overlay``
    (including lists) replaces the value in ``base``.

    Args:
        base: The lower-priority mapping.
        overlay: The higher-priority mapping.

    Returns:
        A new merged dictionary. Neither input is modified.
    """
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def read_yaml(path: Path) -> dict[str, Any]:
    """Reads one YAML file and returns its top-level mapping.

    Args:
        path: File to read.

    Returns:
        The parsed mapping, or an empty dict for an empty file.

    Raises:
        ConfigError: If the file does not contain a mapping.
    """
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")
    return data


def read_yaml_dir(directory: Path) -> list[dict[str, Any]]:
    """Reads every ``*.yaml``/``*.yml`` file in a directory, sorted by name.

    Args:
        directory: Directory to scan. Missing directories yield no files.

    Returns:
        Parsed mappings in file-name order.
    """
    if not directory.is_dir():
        return []
    files = sorted(p for p in directory.iterdir() if p.suffix in {".yaml", ".yml"})
    return [read_yaml(path) for path in files]


def load_layered_config(
    config_dir: Path,
    environment: str,
    overlay_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Loads and merges the base, environment and deployment config layers.

    Args:
        config_dir: Directory holding ``app.yaml`` and ``environments/``.
        environment: Environment name, for example ``dev`` or ``prod``.
        overlay_dir: Optional directory of deployment overlay files.
        environ: Environment used for ``${VAR}`` interpolation.

    Returns:
        The merged, interpolated configuration mapping.

    Raises:
        ConfigError: If ``app.yaml`` does not exist.
    """
    base_file = config_dir / "app.yaml"
    if not base_file.is_file():
        raise ConfigError(f"Base configuration not found: {base_file}")

    merged = read_yaml(base_file)
    env_file = config_dir / "environments" / f"{environment}.yaml"
    if env_file.is_file():
        merged = deep_merge(merged, read_yaml(env_file))
    if overlay_dir is not None:
        for overlay in read_yaml_dir(overlay_dir):
            merged = deep_merge(merged, overlay)
    return interpolate_env(merged, environ)
