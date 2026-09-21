import pytest

from catalog.sources.useragent import build_user_agent


@pytest.mark.parametrize(
    "contact",
    [
        "me@example.com",
        "https://github.com/someone/resonantia",
        "  me@example.com  ",
        "me@example.com\n",
    ],
)
def test_a_contact_becomes_a_descriptive_user_agent(contact: str) -> None:
    agent = build_user_agent(contact)

    assert agent == f"Resonantia/0.1 ({contact.strip()})"


@pytest.mark.parametrize(
    "contact",
    [
        "",
        "   ",
        "nobody",
        "a b@example.com",
        "me@example.com\r\nX-Injected: 1",
        "me@example.com\nX-Injected: 1",
        "me@example.com)(",
        "(me@example.com)",
        "<me@example.com>",
        "me@example.com\x00",
        "x@" + "y" * 300,
        "@",
    ],
)
def test_a_contact_that_could_break_the_header_is_rejected(contact: str) -> None:
    with pytest.raises(ValueError, match="CONTACT_EMAIL"):
        build_user_agent(contact)
