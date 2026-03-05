"""Nova Credential Store — self-managed credentials for learned skills.

Simple JSON file store at data/nova_credentials.json.
Nova can save API keys obtained during skill registration (e.g., Moltbook)
and retrieve them later without human .env editing.

Why not Brain/Memory?
- Credentials are structured key-value data, not semantic/searchable text
- Vector DB search would return partial matches / wrong keys
- Credentials need exact lookup by name, not fuzzy similarity
- Simple JSON is fast, auditable, and reliable

Security:
- File permissions set to 0o600 (owner-only read/write)
- Keys are stored as-is (encryption-at-rest via OS-level disk encryption)
- Only accessed by PluginLoader and SkillLearner — never exposed in prompts
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_CREDENTIALS_FILE = Path("data/nova_credentials.json")


class NovaCredentialStore:
    """Key-value store for Nova's self-managed API credentials.

    Used by:
    - SkillLearner: saves credentials after autonomous API registration
    - PluginLoader: checks here before os.getenv() for plugin env vars
    """

    def __init__(self, path: Path = None):
        self._path = path or _CREDENTIALS_FILE
        self._cache: Dict[str, str] = {}
        self._load()

    def _load(self):
        """Load credentials from disk."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                if isinstance(data, dict):
                    self._cache = data
                    logger.info(f"Loaded {len(self._cache)} credential(s) from {self._path}")
            except Exception as e:
                logger.warning(f"Failed to load credentials: {e}")
                self._cache = {}
        else:
            self._cache = {}

    def get(self, key: str) -> Optional[str]:
        """Get a credential by env var name. Returns None if not found."""
        return self._cache.get(key)

    def set(self, key: str, value: str, source: str = "unknown"):
        """Save a credential.

        Args:
            key: Env var name (e.g., MOLTBOOK_API_KEY)
            value: The credential value
            source: Where this credential came from (e.g., "self_registration")
        """
        self._cache[key] = value
        self._save()
        logger.info(f"Credential saved: {key} (source: {source})")

    def has(self, key: str) -> bool:
        """Check if a credential exists."""
        return key in self._cache

    def delete(self, key: str) -> bool:
        """Remove a credential."""
        if key in self._cache:
            del self._cache[key]
            self._save()
            logger.info(f"Credential deleted: {key}")
            return True
        return False

    def list_keys(self) -> list:
        """Return all stored credential keys (not values)."""
        return list(self._cache.keys())

    def resolve(self, env_var: str) -> Optional[str]:
        """Resolve a credential: check store first, then os.getenv().

        This is the main lookup method used by PluginLoader.
        Priority: nova_credentials.json > .env / environment
        """
        value = self._cache.get(env_var)
        if value:
            return value
        return os.getenv(env_var)

    def _save(self):
        """Persist credentials to disk with restricted permissions."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._path.write_text(json.dumps(self._cache, indent=2))
            # Restrict file permissions (owner read/write only)
            os.chmod(self._path, 0o600)
        except Exception as e:
            logger.error(f"Failed to save credentials: {e}")
