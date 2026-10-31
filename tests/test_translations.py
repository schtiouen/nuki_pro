"""Every translation has the keys and placeholders of the English strings."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

INTEGRATION = Path(__file__).parent.parent / "custom_components" / "nuki_pro"
TRANSLATIONS = INTEGRATION / "translations"
LANGUAGES = ["en", "fr", "de", "es", "nl", "it"]
PLACEHOLDER = re.compile(r"\{\w+\}")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _compare(reference: object, other: object, path: str) -> None:
    assert type(reference) is type(other), path
    if isinstance(reference, dict):
        assert set(reference) == set(other), (path, set(reference) ^ set(other))
        for key, value in reference.items():
            _compare(value, other[key], f"{path}/{key}")
    else:
        assert set(PLACEHOLDER.findall(reference)) == set(
            PLACEHOLDER.findall(other)
        ), (path, reference, other)


def test_strings_match_english() -> None:
    """strings.json is the English source."""
    assert _load(INTEGRATION / "strings.json") == _load(TRANSLATIONS / "en.json")


@pytest.mark.parametrize("language", LANGUAGES)
def test_translation_complete(language: str) -> None:
    """Same keys and placeholders as English, nothing left empty."""
    english = _load(TRANSLATIONS / "en.json")
    translated = _load(TRANSLATIONS / f"{language}.json")
    _compare(english, translated, language)

    def _values(node: object) -> list[str]:
        if isinstance(node, dict):
            return [v for child in node.values() for v in _values(child)]
        return [node]  # type: ignore[list-item]

    assert all(value.strip() for value in _values(translated))


def test_no_unexpected_language_file() -> None:
    """A new translation file must be added to LANGUAGES (and the README)."""
    assert sorted(path.stem for path in TRANSLATIONS.glob("*.json")) == sorted(LANGUAGES)
