"""
crm_google_settings.py
======================

Хранилище настроек Google для CRM-интерфейса.
Путь к настройкам: ~/.excelio_crm_settings.txt

Формат (каждый ключ на новой строке):
    google_client_secret_path=...
    google_folder_id=...
"""
from __future__ import annotations

import os
from pathlib import Path


_SETTINGS_PATH = Path.home() / ".excelio_crm_settings.txt"

_DEFAULTS: dict[str, str] = {
    "google_client_secret_path": "",
    "google_folder_id": "",
}


def load_settings() -> dict[str, str]:
    """Загрузить настройки из файла (или вернуть пустые)."""
    if not _SETTINGS_PATH.is_file():
        return dict(_DEFAULTS)
    result = dict(_DEFAULTS)
    try:
        for line in _SETTINGS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line:
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip()
    except Exception:
        pass
    return result


def save_settings(settings: dict[str, str]) -> None:
    """Сохранить настройки в файл (только непустые значения)."""
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, value in settings.items():
        if value:
            lines.append(f"{key}={value}")
    _SETTINGS_PATH.write_text("\n".join(lines), encoding="utf-8")


def clear_settings() -> None:
    """Удалить файл настроек."""
    _SETTINGS_PATH.unlink(missing_ok=True)
