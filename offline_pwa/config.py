"""Configuration for the full-offline PWA host.

This config is intentionally separate from web_service.config because the PWA
host is only a bootstrap/static/model-file service. Inference runs in the
browser after the first install/download step.
"""

import configparser
import os
import shutil

from core.config import BASE_DIR

CONFIG_FILE = os.path.join(BASE_DIR, "config.ini")
CONFIG_EXAMPLE_FILE = CONFIG_FILE + ".example"
STATIC_DIR = os.path.join(BASE_DIR, "offline_pwa", "static")
MANIFEST_FILE = os.path.join(BASE_DIR, "offline_pwa", "model_manifest.json")


class OfflinePWAConfig:
    """Read/write config.ini [OfflinePWA]."""

    DEFAULTS = {
        "enabled": "true",
        "port": "8444",
        "model_source": "bundled_server",
        "model_proxy_enabled": "false",
        "cache_version": "1",
        "max_model_download_mb": "8192",
    }

    def __init__(self):
        self._config = configparser.ConfigParser()
        self.load()

    def load(self):
        changed = False
        if not os.path.exists(CONFIG_FILE) and os.path.exists(CONFIG_EXAMPLE_FILE):
            shutil.copy2(CONFIG_EXAMPLE_FILE, CONFIG_FILE)

        self._config.clear()
        if os.path.exists(CONFIG_FILE):
            self._config.read(CONFIG_FILE, encoding="utf-8-sig")

        if not self._config.has_section("OfflinePWA"):
            self._config.add_section("OfflinePWA")
            changed = True

        for key, value in self.DEFAULTS.items():
            if not self._config.has_option("OfflinePWA", key):
                self._config.set("OfflinePWA", key, value)
                changed = True

        # Older PWA builds defaulted to HuggingFace proxying. The selected
        # deployment mode now ships model files with the server package, so
        # migrate old default values to local-only unless explicitly changed
        # again by the operator.
        source = self._config.get("OfflinePWA", "model_source", fallback="").strip().lower()
        proxy = self._config.get("OfflinePWA", "model_proxy_enabled", fallback="").strip().lower()
        if source == "huggingface" and proxy in ("1", "true", "yes", "on"):
            self._config.set("OfflinePWA", "model_source", self.DEFAULTS["model_source"])
            self._config.set("OfflinePWA", "model_proxy_enabled", self.DEFAULTS["model_proxy_enabled"])
            changed = True

        if changed:
            self.save()

    def save(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            self._config.write(f)

    def get(self, key: str) -> str:
        return self._config.get("OfflinePWA", key, fallback=self.DEFAULTS.get(key, ""))

    @property
    def enabled(self) -> bool:
        return self.get("enabled").strip().lower() in ("1", "true", "yes", "on")

    @property
    def port(self) -> int:
        return int(self.get("port"))

    @property
    def model_source(self) -> str:
        return self.get("model_source").strip().lower()

    @property
    def model_proxy_enabled(self) -> bool:
        value = self.get("model_proxy_enabled").strip().lower()
        return value in ("1", "true", "yes", "on")

    @property
    def remote_model_downloads_enabled(self) -> bool:
        return self.model_source in ("huggingface", "hf", "remote") and self.model_proxy_enabled

    @property
    def cache_version(self) -> str:
        return self.get("cache_version")

    @property
    def max_model_download_bytes(self) -> int:
        return int(self.get("max_model_download_mb")) * 1024 * 1024

    def to_dict(self) -> dict:
        return {key: self.get(key) for key in self.DEFAULTS}


offline_pwa_config = OfflinePWAConfig()
