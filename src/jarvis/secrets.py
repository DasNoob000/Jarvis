"""API key resolution.

Keys never touch the config file. They come from, in order:

1. an environment variable
2. the OS keychain (macOS Keychain / Windows Credential Manager), via ``keyring``
3. nothing — for Anthropic specifically, that is a legitimate outcome: the SDK will
   fall back to an ``ant auth login`` profile on disk. So a missing key is not by
   itself an error, and we do not prompt for one until a call actually fails.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

KEYRING_SERVICE = "Jarvis"

ANTHROPIC_ENV = "ANTHROPIC_API_KEY"
ANTHROPIC_ACCOUNT = "anthropic_api_key"

ELEVENLABS_ENV = "ELEVENLABS_API_KEY"
ELEVENLABS_ACCOUNT = "elevenlabs_api_key"


def _from_keyring(account: str) -> str | None:
    try:
        import keyring
    except ImportError:
        log.debug("keyring not installed; skipping keychain lookup")
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, account) or None
    except Exception as exc:
        # A locked or unavailable keychain must not be fatal.
        log.warning("keychain lookup for %s failed: %s", account, exc)
        return None


def _resolve(env_var: str, account: str) -> tuple[str | None, str]:
    """Return (key, where_it_came_from)."""
    value = os.environ.get(env_var)
    if value:
        return value.strip(), f"${env_var}"
    value = _from_keyring(account)
    if value:
        return value.strip(), f"keychain ({KEYRING_SERVICE}/{account})"
    return None, "not found"


def anthropic_key() -> tuple[str | None, str]:
    """The Anthropic key, or None to let the SDK resolve its own credentials.

    Returning None is normal and not an error — see the module docstring.
    """
    return _resolve(ANTHROPIC_ENV, ANTHROPIC_ACCOUNT)


def elevenlabs_key() -> tuple[str | None, str]:
    return _resolve(ELEVENLABS_ENV, ELEVENLABS_ACCOUNT)


def store(account: str, value: str) -> None:
    """Save a key to the OS keychain. Used by the settings UI, never automatically."""
    import keyring

    keyring.set_password(KEYRING_SERVICE, account, value)
    log.info("stored %s in the keychain", account)


def credential_hint() -> str:
    """A sentence telling the user how to supply a key. Shown on auth failure."""
    return (
        f"No Anthropic credentials found. Either export {ANTHROPIC_ENV}, store a key "
        f"in the keychain under {KEYRING_SERVICE}/{ANTHROPIC_ACCOUNT}, or run "
        f"`ant auth login`."
    )
