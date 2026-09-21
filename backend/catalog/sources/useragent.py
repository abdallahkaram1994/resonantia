import re

APP_NAME = "Resonantia"
APP_VERSION = "0.1"

# An email address or a URL: no spaces, no control characters, no parentheses (they delimit the
# contact in the header), so a bad value cannot break or inject into the header.
_CONTACT = re.compile(r"[^\s()<>\x00-\x1f\x7f]{3,200}")


def build_user_agent(contact: str) -> str:
    """The descriptive User-Agent MusicBrainz and Wikimedia require, with a way to reach us.

    Both projects ask for `Name/version (contact)` and may block anonymous or generic clients.
    """
    contact = contact.strip()
    if not _CONTACT.fullmatch(contact) or ("@" not in contact and "://" not in contact):
        raise ValueError("CONTACT_EMAIL must be an email address or a URL")
    return f"{APP_NAME}/{APP_VERSION} ({contact})"
