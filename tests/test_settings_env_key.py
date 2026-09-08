"""Regression tests: env-sourced API keys must never be written to config.ini.

With RAWG_API_KEY / THEGAMESDB_API_KEY in the environment the key fields in
Settings are disabled, and ``_save`` used to fall back to
``Config.rawg_api_key`` — which holds the env value — persisting the secret
to disk and destroying the ini's own key. The ini option must be left
untouched whenever the value is env-sourced.

Also covers: ``_save`` must survive a corrupt existing ini
(``configparser.Error`` is not an ``OSError``) and keep the dialog usable.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import warnings

import pytest
from PySide6.QtWidgets import QApplication, QDialog

import playcache.gui.settings_dialog as settings_dialog_module
from playcache.config import Config
from playcache.gui.settings_dialog import SettingsDialog

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(scope="module")
def qapp():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = QApplication.instance() or QApplication([])
    yield app


class _StubMessageBox:
    warnings_shown: list = []

    @staticmethod
    def warning(*args, **kwargs):
        _StubMessageBox.warnings_shown.append(args)
        return None


@pytest.fixture
def stub_message_box(monkeypatch):
    _StubMessageBox.warnings_shown = []
    monkeypatch.setattr(settings_dialog_module, "QMessageBox", _StubMessageBox)
    return _StubMessageBox.warnings_shown


@pytest.fixture(autouse=True)
def clean_key_env(monkeypatch):
    monkeypatch.delenv("RAWG_API_KEY", raising=False)
    monkeypatch.delenv("THEGAMESDB_API_KEY", raising=False)


def _write_ini(path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_env_rawg_key_not_written_to_ini(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("RAWG_API_KEY", "ENV_SECRET_123")
    ini = tmp_path / "config.ini"
    _write_ini(ini, "[rawg]\napi_key = INI_KEY_ABC\n[catalog]\nrequest_delay = 0.3\n")
    config = Config.load(str(ini))
    assert config.rawg_api_key == "ENV_SECRET_123"
    dialog = SettingsDialog(config, config_path=str(ini))
    assert not dialog.rawg_key.isEnabled()
    dialog.delay.setValue(0.5)
    dialog._save()

    content = ini.read_text(encoding="utf-8")
    assert "ENV_SECRET_123" not in content
    assert "INI_KEY_ABC" in content
    assert "request_delay = 0.5" in content
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert config.rawg_api_key == "ENV_SECRET_123"
    assert config.request_delay == 0.5


def test_env_tgdb_key_not_written_to_ini(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("THEGAMESDB_API_KEY", "ENV_TGDB_SECRET")
    ini = tmp_path / "config.ini"
    _write_ini(ini, "[thegamesdb]\napi_key = INI_TGDB_KEY\n")
    config = Config.load(str(ini))
    assert config.thegamesdb_api_key == "ENV_TGDB_SECRET"
    dialog = SettingsDialog(config, config_path=str(ini))
    assert not dialog.tgdb_key.isEnabled()
    dialog.timeout.setValue(30)
    dialog._save()

    content = ini.read_text(encoding="utf-8")
    assert "ENV_TGDB_SECRET" not in content
    assert "INI_TGDB_KEY" in content
    assert "request_timeout = 30" in content
    assert config.thegamesdb_api_key == "ENV_TGDB_SECRET"


def test_editable_key_still_written_to_ini(qapp, tmp_path):
    ini = tmp_path / "config.ini"
    _write_ini(ini, "[rawg]\napi_key = OLD_KEY\n")
    config = Config.load(str(ini))
    dialog = SettingsDialog(config, config_path=str(ini))
    assert dialog.rawg_key.isEnabled()
    dialog.rawg_key.setText("NEW_INI_KEY")
    dialog._save()

    content = ini.read_text(encoding="utf-8")
    assert "NEW_INI_KEY" in content
    assert "OLD_KEY" not in content
    assert config.rawg_api_key == "NEW_INI_KEY"


def test_save_with_corrupt_ini_shows_warning_and_stays_functional(
    qapp, tmp_path, stub_message_box
):
    ini = tmp_path / "config.ini"
    _write_ini(ini, "api_key = missing_section_header\n")
    config = Config()
    dialog = SettingsDialog(config, config_path=str(ini))

    dialog._save()

    assert len(stub_message_box) == 1
    assert "Could not save settings" in stub_message_box[0]
    assert dialog.result() == 0
    assert not ini.with_suffix(".tmp").exists()

    dialog.delay.setValue(0.7)
    dialog._save()
    assert len(stub_message_box) == 2
    assert dialog.result() == 0
