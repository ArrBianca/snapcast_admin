#! /usr/bin/env python
# PYTHON_ARGCOMPLETE_OK
"""Remote control script for the `https://www.peanut.one/snapcast` podcast host.

This script does not ask for confirmation and does not back up data before
destructive commands. Be careful.
"""
from argparse import (
    Action,
    ArgumentError,
    ArgumentParser,
    ArgumentTypeError,
    Namespace,
)
from dataclasses import KW_ONLY, dataclass
from datetime import datetime, timedelta, timezone
from pprint import pprint as pp
from shutil import get_terminal_size
from typing import Any, Iterable, Sequence
from urllib.parse import unquote
from uuid import UUID

from argcomplete import autocomplete, safe_actions  # type:ignore
from argcomplete.completers import SuppressCompleter
from b2sdk.exception import FileNotPresent
from b2sdk.v2 import B2Api, Bucket, InMemoryAccountInfo
from requests import delete, get, patch
from wcwidth import wcwidth

database_fields = (
    'title', 'summary', 'subtitle', 'long_summary', 'media_url', 'media_size',
    'media_type', 'media_duration', 'pub_date', 'link', 'episode_art',
)
B2_APP_KEY_ID = "0051810bbcb180d0000000003"
B2_APP_KEY = "K005NELiDxj5ILjowIzhM7eA5l8qG+s"
b2_base_url = "https://f005.backblazeb2.com/file/jbc-external/"
BEARER_TOKEN = {'Authorization': "Bearer 628c17c9-f2b8-4616-a5fb-f4a9759f32c9"}
BASE_URL = "https://www.peanut.one/snapcast"
# BASE_URL = "http://192.168.1.176:5000/snapcast"
FEED_ID = "1787bd99-9d00-48c3-b763-5837f8652bd9"


class FieldValueAction(Action):
    """Validate and pair off db fields and new values.

    ['title', 'Python 3', 'subtitle', 'The Return'] ->
        [['title', 'Python 3], ['subtitle', 'The Return']]

    ['media_duration', '999', 'pub_date'] ->
        ArgumentError, namespace now contains `fv_partial=True`

    ['titl', 'Python 3'] -> ArgumentError

    If validation passes, the result list is saved to the Namespace.
    """

    def __call__(self,  # noqa D103
                 parser: ArgumentParser,
                 namespace: Namespace,
                 values: str | Sequence[Any] | None,
                 option_string: str | None = None,
                 ) -> None:
        if not values:
            raise ArgumentError(self, "Arguments not present.")

        if len(values) % 2 != 0:
            namespace.fv_partial = True
            raise ArgumentError(self, "Mismatched field value pair")

        pairs = [list(i) for i in zip(*[iter(values)] * 2)]
        if any(pair[0] not in database_fields for pair in pairs):
            raise ArgumentError(
                self, f"field must be one of "f"[{", ".join(database_fields)}]")

        setattr(namespace, self.dest, pairs)


@dataclass
class Episode:  # noqa: D101
    id: int
    title: str
    summary: str
    subtitle: str
    long_summary: str
    media_url: str
    media_size: int
    media_type: str
    media_duration: int | timedelta
    pub_date: str | datetime
    link: str
    episode_art: str
    _: KW_ONLY
    uuid: str
    podcast_uuid: int

    def __post_init__(self) -> None:
        """We perform type conversions if necessary."""
        if isinstance(md := self.media_duration, int):
            self.media_duration: timedelta = timedelta(seconds=md)
        if isinstance(pd := self.pub_date, str):
            self.pub_date = datetime.fromisoformat(pd)


# noinspection PyUnusedLocal
def paired_field_value_completer(
        parsed_args: Namespace, **kwargs: str) -> Iterable[str]:
    """Alternates completion of fields and the values to update.

    If the `FieldValueAction` has the column but not the new value, it leaves
    us a flag in the namespace we can check for. If found, don't complete.
    """
    if hasattr(parsed_args, 'fv_partial'):
        return []
    return database_fields


def episode_id_converter(s: str) -> Iterable[str]:
    """Validate command line episode id or comma-separated list of same.

    :param s: The argument from the command line
    :raises ArgumentTypeError: if any id is invalid.
    :return: A list of episode ids.
    """
    items = s.split(",")
    for item in items:
        try:
            item_id = int(item)
            if not (item_id > 0 or item_id == -1):  # Must be positive or -1
                raise ArgumentTypeError(f"{item_id} is not a valid episode ID")
        except ValueError:
            try:
                UUID(item)
            except ValueError:
                raise ArgumentTypeError(f"{item} is not a valid uuid") from None
    return items


def fwtruncate(s: str, max_width: int, min_width: int = 0) -> str:
    """Truncate a string to a maximum onscreen printed width.

    :param s: The input string.
    :param max_width: The maximum width in characters.
    :param min_width: The minimum width in characters.
    :return: A substring of `s` no wider than `max_width` characters when
        printed to a console
    """
    assert max_width >= min_width
    length = 0
    current_width = 0

    for char in s:
        char_width = wcwidth(char)

        if current_width + char_width > max_width:
            break

        length += 1
        current_width += char_width
    return s[0:max(length, min_width)]


def get_b2() -> tuple[B2Api, Bucket]:
    """Return B2Api object and the `jbc-external` bucket."""
    b2 = B2Api(InMemoryAccountInfo())
    b2.authorize_account("production", B2_APP_KEY_ID, B2_APP_KEY)
    bucket = b2.get_bucket_by_name("jbc-external")
    return b2, bucket


def get_all_episodes() -> Iterable[Episode]:
    """Retrieve all episodes from the server."""
    data = get(
        f"{BASE_URL}/{FEED_ID}/episodes",
        headers=BEARER_TOKEN,
    )
    data.raise_for_status()

    return [Episode(**i) for i in data.json()]


def episode_info(episode_id: str | int) -> Episode:
    """Retrieve all data for the specified episode.

    :param episode_id: The ID of the episode to retrieve information for.
        Either an integer episode number,a UUID, or -1 which returns the latest
        episode.
    :raises ArgumentError: if the ``episode_id`` turns out to be invalid.
    :return: An `Episode` containing data for the ``episode_id``
    """
    response = get(f"{BASE_URL}/{FEED_ID}/episode/{episode_id}")
    if response.status_code == 404:
        raise ArgumentError(None, f"Episode {episode_id} was not found")
    return Episode(**response.json())


def handle_list(args: Namespace) -> None:
    """Process the "list" subcommand from the CLI."""
    episodes = get_all_episodes()

    if args.find:
        episodes = filter(lambda x: args.find in x.title, episodes)

    lines = []
    width = get_terminal_size((0, 0)).columns
    for ep in sorted(episodes, key=lambda x: getattr(x, args.sort)):
        lines.append("│ ".join([
            f"{ep.id:3}",
            f"{ep.pub_date:%Y-%m-%d}",
            f"{ep.media_duration!s:>8}",
            f"{ep.media_size / 1000000:#6.2F} MB",
            f"{fwtruncate(ep.title, width - 38)}" if width else f"{ep.title}",
        ]))
    print(*lines, sep="\n")


def handle_info(args: Namespace) -> None:
    """Process the "info" subcommand from the CLI."""
    pp(episode_info(args.id[0]))


def handle_update(args: Namespace) -> None:
    """Process the "update" subcommand from the CLI."""
    episode_uuids = [episode_info(i).uuid for i in args.id]

    for pair in args.set:
        match pair[0]:
            case "media_duration":
                # Convert [[HH:]MM:]SS to integer seconds.
                pair[1] = sum(60 ** i * int(v) for i, v in
                              enumerate(pair[1].split(":")[::-1]))
            case "pub_date":
                # Convert local "YYYY-MM-DD[ HH:MM]" to full spec UTC string.
                d = datetime.fromisoformat(pair[1])
                pair[1] = d.astimezone(timezone.utc).isoformat()

    for episode_uuid in episode_uuids:
        patch(
            f"{BASE_URL}/{FEED_ID}/episode/{episode_uuid}",
            json=dict(args.set),
            headers=BEARER_TOKEN,
        )


def handle_delete(args: Namespace) -> None:
    """Process the "delete" subcommand from the CLI."""
    episode = episode_info(args.id[0])

    delete(
        f"{BASE_URL}/{FEED_ID}/episode/{episode.uuid}",
        headers=BEARER_TOKEN,
    )

    _, bucket = get_b2()
    filename = unquote(episode.media_url.split("/")[-1])

    while True:  # Delete until no file versions remain
        try:
            bucket.get_file_info_by_name(filename).delete()
        except FileNotPresent:
            break

    print(f"Episode entry #{args.id[0]} successfuly deleted")


def run() -> None:
    """Script entry point."""
    admin_parser = ArgumentParser()
    subparsers = admin_parser.add_subparsers()

    # -------- LIST --------------------
    list_parser = subparsers.add_parser(
        "list",
        help="list all episodes",
    )
    list_parser.add_argument(
        "--sort",
        help="sort results. default: %(default)s",
        choices=('pub_date', 'id'),
        default='pub_date',
    )
    list_parser.add_argument(
        "--find",
        help="filter output to results containing FIND",
    )

    # -------- INFO --------------------
    info_parser = subparsers.add_parser(
        "info",
        help="get episode information",
    )
    info_parser.add_argument(  # type: ignore
        "id",
        help="id or uuid of the episode to fetch, or -1 for most recent",
        type=episode_id_converter,
    ).completer = SuppressCompleter

    # -------- UPDATE --------------------
    update_parser = subparsers.add_parser(
        "update",
        help="update a field of an episode",
        usage="%(prog)s id[,id...] field value [field value...]",
    )
    update_parser.add_argument(  # type: ignore
        "id",
        help="id or uuid of the episode to update",
        type=episode_id_converter,
    ).completer = SuppressCompleter
    update_parser.add_argument(  # type: ignore
        "set",
        help="database column and new value pair",
        action=FieldValueAction,
        metavar="<field value>",
        nargs='*',
    ).completer = paired_field_value_completer

    # -------- DELETE --------------------
    delete_parser = subparsers.add_parser(
        "delete",
        help="delete episodes",
    )
    delete_parser.add_argument(  # type: ignore
        "id",
        help="id or uuid of the episode to delete",
        type=episode_id_converter,
    ).completer = SuppressCompleter

    list_parser.set_defaults(func=handle_list)
    info_parser.set_defaults(func=handle_info)
    update_parser.set_defaults(func=handle_update)
    delete_parser.set_defaults(func=handle_delete)

    # This is a lie, we absolutely have side-effects. It's necessary for the
    # completer to work though as the errors we'd want to throw on incorrect
    # input during normal execution would leave the completer with no context.
    safe_actions.add(FieldValueAction)
    autocomplete(admin_parser, exclude=["-h", "--help"])
    arguments = admin_parser.parse_args()

    if hasattr(arguments, "func"):
        try:
            arguments.func(arguments)
        except ArgumentError as err:
            print(err)


if __name__ == '__main__':
    run()
