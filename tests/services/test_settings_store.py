"""Characterisation tests for SettingsStore.

These pin the behaviour of the seven hand-rolled settings.json read/write sites
catalogued in docs/UI_FEATURE_INVENTORY.md section 3.7:

  onboarding.save_settings          write, indent=2, replaces the whole document
  onboarding.needs_onboarding       read, unguarded
  app.update_library                read, unguarded
  settings_window.load_settings     read, unguarded
  settings_window.change_xml_path   read-modify-write, indent=2, preserves other keys
  settings_window.update_library    read, unguarded
  settings_window.full_reindex      read, unguarded

Every site guards a *missing* file with an exists() check and takes a "not
configured" branch. No site wraps json.load in a try, so a *corrupt* file raises
JSONDecodeError. SettingsStore reproduces both exactly; neither is improved here.
"""

import json

import pytest

from services.settings_store import SettingsStore


def test_get_returns_persisted_value(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"xml_path": "/tmp/library.xml"}))

    assert SettingsStore(path).get("xml_path") == "/tmp/library.xml"


def test_set_then_get_round_trips_through_disk(tmp_path):
    path = tmp_path / "settings.json"

    SettingsStore(path).set("xml_path", "/tmp/library.xml")

    assert SettingsStore(path).get("xml_path") == "/tmp/library.xml"


def test_set_persists_immediately_with_indent_two(tmp_path):
    """settings_window.change_xml_path and onboarding.save_settings both use indent=2."""
    path = tmp_path / "settings.json"

    SettingsStore(path).set("xml_path", "/tmp/library.xml")

    assert path.read_text() == '{\n  "xml_path": "/tmp/library.xml"\n}'


def test_set_preserves_other_keys(tmp_path):
    """Matches settings_window.change_xml_path, which merges into the existing dict."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"xml_path": "/old.xml", "first_run_complete": True}))

    SettingsStore(path).set("xml_path", "/new.xml")

    assert json.loads(path.read_text()) == {
        "xml_path": "/new.xml",
        "first_run_complete": True,
    }


def test_get_returns_default_for_missing_key(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"first_run_complete": True}))

    assert SettingsStore(path).get("xml_path", "Not set") == "Not set"


def test_get_returns_none_when_no_default_given(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({}))

    assert SettingsStore(path).get("xml_path") is None


def test_missing_file_is_tolerated_and_reads_as_empty(tmp_path):
    """Every current site guards on exists() and treats absence as 'not configured'."""
    store = SettingsStore(tmp_path / "does_not_exist.json")

    assert store.all() == {}
    assert store.get("xml_path") is None
    assert store.get("xml_path", "Not set") == "Not set"
    assert store.xml_path is None


def test_set_creates_the_file_when_missing(tmp_path):
    path = tmp_path / "settings.json"

    SettingsStore(path).set("xml_path", "/tmp/library.xml")

    assert path.exists()
    assert json.loads(path.read_text()) == {"xml_path": "/tmp/library.xml"}


def test_corrupt_file_raises_json_decode_error(tmp_path):
    """CURRENT BEHAVIOUR, NOT A BUG FIX. No existing site wraps json.load in a try,
    so a corrupt settings.json propagates JSONDecodeError - out of
    needs_onboarding() it crashes startup before any window is shown. Fixing this
    is rewrite work; spec 3.2 / backlog."""
    path = tmp_path / "settings.json"
    path.write_text("{not valid json")

    store = SettingsStore(path)

    with pytest.raises(json.JSONDecodeError):
        store.all()
    with pytest.raises(json.JSONDecodeError):
        store.get("xml_path")


def test_set_on_a_corrupt_file_also_raises(tmp_path):
    """change_xml_path reads before merging, so it fails the same way."""
    path = tmp_path / "settings.json"
    path.write_text("{not valid json")

    with pytest.raises(json.JSONDecodeError):
        SettingsStore(path).set("xml_path", "/tmp/library.xml")


def test_all_returns_the_whole_document(tmp_path):
    path = tmp_path / "settings.json"
    payload = {"xml_path": "/tmp/library.xml", "first_run_complete": True}
    path.write_text(json.dumps(payload))

    assert SettingsStore(path).all() == payload


def test_all_returns_a_copy_that_does_not_write_back(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"xml_path": "/tmp/library.xml"}))
    store = SettingsStore(path)

    store.all()["xml_path"] = "/mutated.xml"

    assert store.get("xml_path") == "/tmp/library.xml"


def test_xml_path_property_reads_the_only_key_in_use(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"xml_path": "/tmp/library.xml"}))

    assert SettingsStore(path).xml_path == "/tmp/library.xml"


def test_xml_path_is_none_when_unset(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"first_run_complete": True}))

    assert SettingsStore(path).xml_path is None


def test_replace_overwrites_the_whole_document(tmp_path):
    """onboarding.save_settings writes {xml_path, first_run_complete} wholesale,
    discarding any other key. set() merges; replace() does not. Both are kept so
    each call site keeps its exact current semantics."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"xml_path": "/old.xml", "stray_key": 1}))

    SettingsStore(path).replace({"xml_path": "/new.xml", "first_run_complete": True})

    assert json.loads(path.read_text()) == {
        "xml_path": "/new.xml",
        "first_run_complete": True,
    }


def test_replace_writes_indent_two(tmp_path):
    path = tmp_path / "settings.json"

    SettingsStore(path).replace({"xml_path": "/new.xml", "first_run_complete": True})

    assert path.read_text() == (
        '{\n  "xml_path": "/new.xml",\n  "first_run_complete": true\n}'
    )


def test_reads_are_not_cached_across_external_writes(tmp_path):
    """Each current site opens settings.json afresh; SettingsWindow and the main
    window can therefore disagree only until the next read."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"xml_path": "/first.xml"}))
    store = SettingsStore(path)
    assert store.get("xml_path") == "/first.xml"

    path.write_text(json.dumps({"xml_path": "/second.xml"}))

    assert store.get("xml_path") == "/second.xml"


def test_accepts_a_string_path(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"xml_path": "/tmp/library.xml"}))

    assert SettingsStore(str(path)).get("xml_path") == "/tmp/library.xml"
