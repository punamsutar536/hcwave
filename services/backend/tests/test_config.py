from pathlib import Path

import pytest

from hcwave.config.loader import ConfigError, deep_merge, interpolate_env, load_layered_config


def test_interpolate_env_with_defaults():
    env = {"A": "1"}
    assert interpolate_env("x-${A}-${B:-two}-${C}", env) == "x-1-two-"
    assert interpolate_env({"k": ["${A}", {"n": "${B:-b}"}]}, env) == {"k": ["1", {"n": "b"}]}


def test_deep_merge_merges_nested_and_replaces_lists():
    base = {"a": {"b": 1, "c": [1, 2]}, "d": 1}
    merged = deep_merge(base, {"a": {"c": [3], "e": 2}})
    assert merged == {"a": {"b": 1, "c": [3], "e": 2}, "d": 1}
    assert base["a"]["c"] == [1, 2]  # input untouched


def test_layered_config(tmp_path: Path):
    (tmp_path / "environments").mkdir()
    (tmp_path / "app.yaml").write_text("x: {a: 1, b: '${V:-v}'}\n")
    (tmp_path / "environments" / "prod.yaml").write_text("x: {a: 2}\n")
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    (overlay / "z.yaml").write_text("x: {c: 3}\n")
    assert load_layered_config(tmp_path, "prod", overlay, {"V": "env"}) == {
        "x": {"a": 2, "b": "env", "c": 3}
    }


def test_missing_base_config_raises(tmp_path: Path):
    with pytest.raises(ConfigError):
        load_layered_config(tmp_path, "dev")


def test_repository_config_loads(container):
    settings = container.settings
    assert settings.messaging.provider == "console"
    assert "demo-hospital" in settings.hospitals
    assert (
        settings.templates["appointment_reminder_24h"]
        .buttons[0]
        .value.startswith("remind_confirm:")
    )
    for lang in ("en", "ml", "hi"):
        assert settings.locales[lang]["menu.book"]
    # Every English key has a Malayalam and Hindi translation.
    missing = {
        lang: set(settings.locales["en"])
        - set(settings.locales[lang])
        - {k for k in settings.locales["en"] if k.startswith("menu.query.")}
        for lang in ("ml", "hi")
    }
    assert missing == {"ml": set(), "hi": set()}
