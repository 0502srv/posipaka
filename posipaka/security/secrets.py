"""SecretsManager — безпечне зберігання секретів."""

from __future__ import annotations

import json
import os
from pathlib import Path

from loguru import logger


class SecretsManager:
    """
    Порядок зберігання (найбезпечніший → найменш безпечний):
    1. OS Keyring (keyring library) — якщо доступний
    2. Encrypted file (~/.posipaka/.secrets.enc) — AES-256
    3. Environment variables — для Docker/systemd
    """

    SERVICE_NAME = "posipaka"

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._secrets_file = data_dir / ".secrets.enc"
        self._keyring_available = self._check_keyring()
        self._cache: dict[str, str] = {}
        self._encryption_key: bytes | None = None

    def _check_keyring(self) -> bool:
        try:
            import keyring  # noqa: F401

            return True
        except ImportError:
            return False

    def get(self, key: str) -> str | None:
        """Отримати секрет. Ніколи не логує значення."""
        # 1. Cache
        if key in self._cache:
            return self._cache[key]

        # 2. Env var
        env_val = os.environ.get(key)
        if env_val:
            self._cache[key] = env_val
            return env_val

        # 3. Keyring
        if self._keyring_available:
            try:
                import keyring

                val = keyring.get_password(self.SERVICE_NAME, key)
                if val:
                    self._cache[key] = val
                    return val
            except Exception:
                pass

        # 4. Encrypted file
        secrets = self._load_encrypted()
        if key in secrets:
            self._cache[key] = secrets[key]
            return secrets[key]

        return None

    def set(self, key: str, value: str) -> None:
        """Зберегти секрет."""
        self._cache[key] = value

        if self._keyring_available:
            try:
                import keyring

                keyring.set_password(self.SERVICE_NAME, key, value)
                logger.debug(f"Secret '{key}' saved to keyring")
                return
            except Exception:
                pass

        # Fallback to encrypted file
        secrets = self._load_encrypted()
        secrets[key] = value
        self._save_encrypted(secrets)
        logger.debug(f"Secret '{key}' saved to encrypted file")

    def delete(self, key: str) -> None:
        """Видалити секрет."""
        self._cache.pop(key, None)

        if self._keyring_available:
            try:
                import keyring

                keyring.delete_password(self.SERVICE_NAME, key)
            except Exception:
                pass

        secrets = self._load_encrypted()
        if key in secrets:
            del secrets[key]
            self._save_encrypted(secrets)

    def list_keys(self) -> list[str]:
        """Список ключів (без значень!)."""
        keys = set(self._cache.keys())
        secrets = self._load_encrypted()
        keys.update(secrets.keys())
        return sorted(keys)

    def _get_encryption_key(self) -> bytes:
        """Отримати або створити ключ шифрування."""
        if self._encryption_key:
            return self._encryption_key

        key_file = self._data_dir / ".encryption_key"
        if key_file.exists():
            self._encryption_key = key_file.read_bytes()
        else:
            from cryptography.fernet import Fernet

            self._encryption_key = Fernet.generate_key()
            key_file.write_bytes(self._encryption_key)
            key_file.chmod(0o600)

        return self._encryption_key

    def _load_encrypted(self) -> dict[str, str]:
        """Завантажити секрети з зашифрованого файлу."""
        if not self._secrets_file.exists():
            return {}
        try:
            from cryptography.fernet import Fernet

            key = self._get_encryption_key()
            f = Fernet(key)
            encrypted = self._secrets_file.read_bytes()
            decrypted = f.decrypt(encrypted)
            return json.loads(decrypted)
        except Exception as e:
            logger.warning(f"Cannot decrypt secrets file: {e}")
            return {}

    def _save_encrypted(self, secrets: dict[str, str]) -> None:
        """Зберегти секрети в зашифрований файл."""
        from cryptography.fernet import Fernet

        key = self._get_encryption_key()
        f = Fernet(key)
        data = json.dumps(secrets).encode()
        encrypted = f.encrypt(data)
        self._secrets_file.write_bytes(encrypted)
        self._secrets_file.chmod(0o600)
