"""i18n catalog sanity: every key has both languages, placeholders match."""
from __future__ import annotations

import re

from bot.i18n import CATALOG, LANGS, norm_lang, t

_PLACEHOLDER_RE = re.compile(r"\{(\w+)")


def test_every_key_has_all_langs():
    for key, entry in CATALOG.items():
        for lang in LANGS:
            assert lang in entry and entry[lang], f"{key} missing {lang}"


def test_placeholders_match_across_langs():
    for key, entry in CATALOG.items():
        ru = set(_PLACEHOLDER_RE.findall(entry["ru"]))
        en = set(_PLACEHOLDER_RE.findall(entry["en"]))
        assert ru == en, f"{key}: placeholders differ ru={ru} en={en}"


def test_norm_lang():
    assert norm_lang("ru") == "ru"
    assert norm_lang("ru-RU") == "ru"
    assert norm_lang("en") == "en"
    assert norm_lang("de") == "en"
    assert norm_lang(None) == "en"


def test_t_formats():
    assert "5" in t("en", "reply.limit_reached", limit=5)
    assert "10" in t("ru", "reply.limit_reached", limit=10)


def test_t_falls_back_to_english():
    assert t("de", "btn.help") == CATALOG["btn.help"]["en"]
