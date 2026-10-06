from __future__ import annotations

import io

from laqta_agent import settings as settings_module
from laqta_agent.settings import Settings, load_settings, save_settings


def test_arabic_folder_name_round_trips_under_a_cp1252_default(tmp_path, monkeypatch):
    """English-locale Windows defaults text files to cp1252, which can't
    encode Arabic -- an Arabic folder name crashed saving the settings.
    Simulated here by making pathlib's default ("locale") encoding cp1252.
    """
    monkeypatch.setattr(settings_module, "_settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(io, "text_encoding", lambda encoding, stacklevel=2: encoding or "cp1252")

    folder = r"C:\Users\photographer\Pictures\الصور"
    save_settings(Settings(folder=folder, locale="ar"))

    assert load_settings().folder == folder
