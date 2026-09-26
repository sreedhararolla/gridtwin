"""Seam B (pure domain): settings parsing has no IO."""

from gridtwin.settings import Settings


def test_cors_origin_list_splits_and_strips():
    s = Settings(cors_origins="http://a.test, http://b.test ,http://c.test")
    assert s.cors_origin_list == ["http://a.test", "http://b.test", "http://c.test"]


def test_cors_origin_list_empty_string_is_empty_list():
    s = Settings(cors_origins="")
    assert s.cors_origin_list == []
