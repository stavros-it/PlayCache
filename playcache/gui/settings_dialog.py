"""Settings dialog for API keys and scan parameters."""
from __future__ import annotations

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
        # Prefer the path recorded by Config.load(); fall back to CWD.
        self._config_path = (
            Path(config_path) if config_path
            else Path(getattr(config, "config_path", "") or Path.cwd() / "config.ini")
        )

        layout = QVBoxLayout(self)
        title = QLabel(
            f"Settings are saved to:\n{self._config_path}\n"
            "Environment variables (RAWG_API_KEY, THEGAMESDB_API_KEY) take priority."
        )
        title.setWordWrap(True)
        layout.addWidget(title)

        form = QFormLayout()

        self.rawg_key = QLineEdit(config.rawg_api_key)
        self.rawg_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.rawg_key.setPlaceholderText("Optional fallback key (rawg.io/apiauth)")
        form.addRow("RAWG API key:", self.rawg_key)

        self.tgdb_key = QLineEdit(config.thegamesdb_api_key)
        self.tgdb_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.tgdb_key.setPlaceholderText("Primary source — get a key at api.thegamesdb.net/key.php")
        form.addRow("TheGamesDB API key:", self.tgdb_key)

        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.0, 10.0)
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

    # ------------------------------------------------------------------ #
    def _save(self) -> None:
        # Snapshot the new values WITHOUT mutating the live config yet — only
        # mutate after the file write succeeds, so a failed save doesn't leave
        # the in-memory config inconsistent with the persisted file.
        new_rawg = self.rawg_key.text().strip()
        new_tgdb = self.tgdb_key.text().strip()
        new_delay = self.delay.value()
        new_timeout = self.timeout.value()
        new_retries = self.retries.value()
        new_threshold = self.threshold.value()
        new_desc_max = self.desc_max.value()

        # Persist to config.ini via an atomic write (temp file + replace).
        try:
            from configparser import ConfigParser
            parser = ConfigParser()
            if self._config_path.is_file():
                parser.read(self._config_path, encoding="utf-8")
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
            with tmp.open("w", encoding="utf-8") as fh:
                parser.write(fh)
            tmp.replace(self._config_path)
        except OSError as e:
            QMessageBox.warning(self, "Could not save settings", str(e))
            return
        # File write succeeded — now mutate the in-memory config.
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
