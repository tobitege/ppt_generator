import keyring
from keyring.errors import KeyringError

SERVICE_NAME = "ppt_generator.llm_keys"


def _account_name(provider):
    return f"provider:{provider}"


def _profile_account_name(profile_name):
    return f"profile:{profile_name.strip()}"


def get_api_key(provider):
    try:
        return keyring.get_password(SERVICE_NAME, _account_name(provider)) or ""
    except KeyringError as exc:
        raise RuntimeError(f"Failed to read encrypted API key for provider '{provider}'.") from exc


def set_api_key(provider, api_key):
    try:
        keyring.set_password(SERVICE_NAME, _account_name(provider), api_key)
    except KeyringError as exc:
        raise RuntimeError(f"Failed to store encrypted API key for provider '{provider}'.") from exc


def delete_api_key(provider):
    try:
        keyring.delete_password(SERVICE_NAME, _account_name(provider))
    except keyring.errors.PasswordDeleteError:
        return
    except KeyringError as exc:
        raise RuntimeError(f"Failed to delete encrypted API key for provider '{provider}'.") from exc


def get_api_key_for_profile(profile_name):
    try:
        return keyring.get_password(SERVICE_NAME, _profile_account_name(profile_name)) or ""
    except KeyringError as exc:
        raise RuntimeError(f"Failed to read encrypted API key for profile '{profile_name}'.") from exc


def set_api_key_for_profile(profile_name, api_key):
    try:
        keyring.set_password(SERVICE_NAME, _profile_account_name(profile_name), api_key)
    except KeyringError as exc:
        raise RuntimeError(f"Failed to store encrypted API key for profile '{profile_name}'.") from exc


def delete_api_key_for_profile(profile_name):
    try:
        keyring.delete_password(SERVICE_NAME, _profile_account_name(profile_name))
    except keyring.errors.PasswordDeleteError:
        return
    except KeyringError as exc:
        raise RuntimeError(f"Failed to delete encrypted API key for profile '{profile_name}'.") from exc
