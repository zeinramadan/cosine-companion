from unittest.mock import Mock

import pytest

import ui.app as app_module


def test_load_app_data_shows_recovery_dialog_for_inconsistent_index(monkeypatch) -> None:
    parent = Mock()
    showerror = Mock()

    def raise_inconsistent_data():
        raise ValueError("ids.json contains 2 track IDs but index.npy has 3 rows")

    monkeypatch.setattr(app_module, "load_all", raise_inconsistent_data)
    monkeypatch.setattr(app_module.messagebox, "showerror", showerror)

    with pytest.raises(SystemExit, match="1"):
        app_module._load_app_data(parent)

    parent.destroy.assert_called_once_with()
    title, message = showerror.call_args.args
    assert title == "Inconsistent Index Data"
    assert "index <rekordbox.xml> --force" in message
    assert "ids.json contains 2 track IDs" in message
    assert showerror.call_args.kwargs == {"parent": parent}
