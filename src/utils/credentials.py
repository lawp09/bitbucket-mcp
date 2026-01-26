"""Secure credentials management with keychain fallback."""

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import keyring for system keychain support
try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    logger.debug("keyring not installed - keychain support disabled")

SERVICE_NAME = "bitbucket-mcp"


@dataclass
class BitbucketCredentials:
    """Bitbucket authentication credentials."""
    username: str
    token: str
    workspace: str


def get_credential(key: str, keyring_key: Optional[str] = None) -> Optional[str]:
    """
    Get a credential value with fallback chain.

    Priority:
    1. Environment variable
    2. System keychain (if keyring installed)

    Args:
        key: Environment variable name (e.g., "BITBUCKET_TOKEN")
        keyring_key: Key name in keychain (defaults to lowercase of env var)

    Returns:
        Credential value or None if not found
    """
    # 1. Environment variable (highest priority)
    if value := os.environ.get(key):
        return value

    # 2. System keychain (if available)
    if KEYRING_AVAILABLE:
        keyring_key = keyring_key or key.lower()
        try:
            if value := keyring.get_password(SERVICE_NAME, keyring_key):
                logger.debug(f"Retrieved {key} from system keychain")
                return value
        except Exception as e:
            logger.warning(f"Failed to read from keychain: {e}")

    return None


def get_credentials() -> BitbucketCredentials:
    """
    Get Bitbucket credentials from environment or keychain.

    Returns:
        BitbucketCredentials object

    Raises:
        ValueError: If required credentials are missing
    """
    username = get_credential("BITBUCKET_USERNAME")
    token = get_credential("BITBUCKET_TOKEN")
    workspace = get_credential("BITBUCKET_WORKSPACE")

    missing = []
    if not username:
        missing.append("BITBUCKET_USERNAME")
    if not token:
        missing.append("BITBUCKET_TOKEN")
    if not workspace:
        missing.append("BITBUCKET_WORKSPACE")

    if missing:
        raise ValueError(
            f"Missing required credentials: {', '.join(missing)}. "
            f"Set as environment variables or store in system keychain."
        )

    return BitbucketCredentials(username=username, token=token, workspace=workspace)


def store_credential(key: str, value: str) -> bool:
    """
    Store a credential in the system keychain.

    Args:
        key: Credential key (e.g., "bitbucket_token")
        value: Credential value

    Returns:
        True if stored successfully, False otherwise
    """
    if not KEYRING_AVAILABLE:
        logger.error("keyring not installed - cannot store in keychain")
        return False

    try:
        keyring.set_password(SERVICE_NAME, key, value)
        logger.info(f"Stored {key} in system keychain")
        return True
    except Exception as e:
        logger.error(f"Failed to store in keychain: {e}")
        return False


def delete_credential(key: str) -> bool:
    """
    Delete a credential from the system keychain.

    Args:
        key: Credential key to delete

    Returns:
        True if deleted successfully, False otherwise
    """
    if not KEYRING_AVAILABLE:
        logger.error("keyring not installed - cannot delete from keychain")
        return False

    try:
        keyring.delete_password(SERVICE_NAME, key)
        logger.info(f"Deleted {key} from system keychain")
        return True
    except Exception as e:
        logger.error(f"Failed to delete from keychain: {e}")
        return False


def is_keyring_available() -> bool:
    """Check if keyring support is available."""
    return KEYRING_AVAILABLE
