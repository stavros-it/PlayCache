"""Settings dialog for API keys and scan parameters."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import Config


class SettingsDialog(QDialog):
    """Edit config values and persist them back to config.ini."""

    def __init__(self, config: Config, config_path: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self._config = config
        self._config_path = (
            Path(config_path) if config_path
            else Path(getattr(config, "config_path", "") or Path.cwd() / "config.ini")
        )

        self._rawg_from_env = bool(os.getenv("RAWG_API_KEY"))
        self._tgdb_from_env = bool(os.getenv("THEGAMESDB_API_KEY"))

        layout = QVBoxLayout(self)
        env_note = (
            "Environment variables (RAWG_API_KEY, THEGAMESDB_API_KEY) take "
            "priority over the file."
        )
        if self._rawg_from_env or self._tgdb_from_env:
            env_sources = []
            if self._rawg_from_env:
                env_sources.append("RAWG_API_KEY")
            if self._tgdb_from_env:
                env_sources.append("THEGAMESDB_API_KEY")
            env_note = (
                f"Keys set via environment variable ({', '.join(env_sources)}) "
                f"are NOT shown here and will NOT be written to config.ini. "
                f"Clear the env var to edit the file value."
            )
        title = QLabel(
            f"Settings are saved to:\n{self._config_path}\n{env_note}"
        )
        title.setWordWrap(True)
        layout.addWidget(title)

        form = QFormLayout()

        if self._rawg_from_env:
            self.rawg_key = QLineEdit()
            self.rawg_key.setEchoMode(QLineEdit.EchoMode.Password)
            self.rawg_key.setPlaceholderText("Set via RAWG_API_KEY env var — not editable here")
            self.rawg_key.setEnabled(False)
        else:
            self.rawg_key = QLineEdit(config.rawg_api_key)
            self.rawg_key.setEchoMode(QLineEdit.EchoMode.Password)
            self.rawg_key.setPlaceholderText("Get a FREE key at rawg.io")
        form.addRow("RAWG API key:", self.rawg_key)

        if self._tgdb_from_env:
            self.tgdb_key = QLineEdit()
            self.tgdb_key.setEchoMode(QLineEdit.EchoMode.Password)
            self.tgdb_key.setPlaceholderText("Set via THEGAMESDB_API_KEY env var — not editable here")
            self.tgdb_key.setEnabled(False)
        else:
            self.tgdb_key = QLineEdit(config.thegamesdb_api_key)
            self.tgdb_key.setEchoMode(QLineEdit.EchoMode.Password)
            self.tgdb_key.setPlaceholderText("Get a FREE key at thegamesdb.net")
        form.addRow("TheGamesDB API key:", self.tgdb_key)

        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.1, 10.0)
        self.delay.setSingleStep(0.1)
        self.delay.setValue(config.request_delay)
        self.delay.setSuffix(" s")
        form.addRow("Request delay:", self.delay)

        self.timeout = QSpinBox()
        self.timeout.setRange(5, 120)
        self.timeout.setValue(config.request_timeout)
        self.timeout.setSuffix(" s")
        form.addRow("Request timeout:", self.timeout)

        self.retries = QSpinBox()
        self.retries.setRange(1, 10)
        self.retries.setValue(config.max_retries)
        form.addRow("Max retries:", self.retries)

        self.threshold = QSpinBox()
        self.threshold.setRange(0, 100)
        self.threshold.setValue(config.fuzzy_threshold)
        self.threshold.setSuffix(" %")
        form.addRow("Fuzzy match threshold:", self.threshold)

        self.desc_max = QSpinBox()
        self.desc_max.setRange(40, 1000)
        self.desc_max.setSingleStep(20)
        self.desc_max.setValue(config.description_max_chars)
        form.addRow("Description max chars:", self.desc_max)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        new_rawg = self.rawg_key.text().strip() if self.rawg_key.isEnabled() else self._config.rawg_api_key
        new_tgdb = self.tgdb_key.text().strip() if self.tgdb_key.isEnabled() else self._config.thegamesdb_api_key
        new_delay = self.delay.value()
        new_timeout = self.timeout.value()
        new_retries = self.retries.value()
        new_threshold = self.threshold.value()
        new_desc_max = self.desc_max.value()

        try:
            from configparser import ConfigParser
            parser = ConfigParser()
            if self._config_path.is_file():
                parser.read(self._config_path, encoding="utf-8-sig")
            for section in ("rawg", "thegamesdb", "catalog"):
                if not parser.has_section(section):
                    parser.add_section(section)
            parser.set("rawg", "api_key", new_rawg)
            parser.set("thegamesdb", "api_key", new_tgdb)
            parser.set("catalog", "request_delay", str(new_delay))
            parser.set("catalog", "request_timeout", str(new_timeout))
            parser.set("catalog", "max_retries", str(new_retries))
            parser.set("catalog", "fuzzy_threshold", str(new_threshold))
            parser.set("catalog", "description_max_chars", str(new_desc_max))
            parser.set("catalog", "db_path", self._config.db_path)
            parser.set(
                "catalog", "skip_folders",
                ",".join(self._config.skip_folders) if self._config.skip_folders else "",
            )
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._config_path.with_suffix(".tmp")
            try:
                with tmp.open("w", encoding="utf-8") as fh:
                    parser.write(fh)
                tmp.replace(self._config_path)
            except OSError:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
                raise
        except OSError as e:
            QMessageBox.warning(self, "Could not save settings", str(e))
            return
        self._config.rawg_api_key = new_rawg
        self._config.thegamesdb_api_key = new_tgdb
        self._config.request_delay = new_delay
        self._config.request_timeout = new_timeout
        self._config.max_retries = new_retries
        self._config.fuzzy_threshold = new_threshold
        self._config.description_max_chars = new_desc_max
        self._config.config_path = str(self._config_path)
        self.accept()

    @property
    def config(self) -> Config:
        return self._config
