from os import environ

from b2sdk.account_info.in_memory import InMemoryAccountInfo
from b2sdk.api import B2Api
from b2sdk.bucket import Bucket
from wcwidth import wcwidth


def get_b2() -> tuple[B2Api, Bucket]:
    """Return B2Api object and the `jbc-external` bucket."""
    b2 = B2Api(InMemoryAccountInfo())
    b2.authorize_account(
        environ["SNADMIN_B2_APP_KEY_ID"],
        environ["SNADMIN_B2_APP_KEY"],
        "production",
    )
    bucket = b2.get_bucket_by_name("jbc-external")
    return b2, bucket


def fwtruncate(s: str, max_width: int, min_width: int = 0) -> str:
    """Truncate a string to a maximum onscreen printed width.

    :param s: The input string.
    :param max_width: The maximum width in characters.
    :param min_width: The minimum width in characters.
    :return: A substring of `s` no wider than `max_width` characters when
        printed to a console
    """
    if min_width > max_width:
        msg = "min_width must not be more than max_width"
        raise ValueError(msg)
    length = 0
    current_width = 0

    for char in s:
        char_width = wcwidth(char)

        if current_width + char_width > max_width:
            break

        length += 1
        current_width += char_width
    return s[0:max(length, min_width)]


class InvalidIdError(Exception):
    """Exception raised when an invalid id is provided to the script."""

    def __init__(self, episode_id: str) -> None:
        super().__init__(f"Episode {episode_id} was not found.")
