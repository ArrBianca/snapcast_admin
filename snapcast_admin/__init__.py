#! /usr/bin/env python
# PYTHON_ARGCOMPLETE_OK
"""Remote control script for the `https://www.peanut.one/snapcast` podcast host.

This script does not ask for confirmation and does not back up data before
destructive commands. Be careful.
"""

from dataclasses import KW_ONLY, dataclass
from datetime import datetime, timedelta, timezone
from pprint import pformat as pf
from shutil import get_terminal_size
from typing import Iterable, Optional
from urllib.parse import unquote
from uuid import UUID

import click
import requests
from b2sdk.exception import FileNotPresent

from .util import fwtruncate, get_b2

database_fields = (
    'title', 'summary', 'subtitle', 'long_summary', 'media_url', 'media_size',
    'media_type', 'media_duration', 'pub_date', 'link', 'episode_art',
)
b2_base_url = "https://f005.backblazeb2.com/file/jbc-external/"
BEARER_TOKEN = {'Authorization': "Bearer 628c17c9-f2b8-4616-a5fb-f4a9759f32c9"}
BASE_URL = "https://www.peanut.one/snapcast"
# BASE_URL = "http://192.168.1.176:5000/snapcast"
FEED_ID = "1787bd99-9d00-48c3-b763-5837f8652bd9"


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


class EpisodeIdType(click.ParamType):  # noqa: D101
    name = "episode id"

    def convert(
            self, value: str,
            param: Optional[click.Parameter],
            ctx: Optional[click.Context],
    ) -> str:
        """Validate command line episode id or comma-separated list of same.

        :param value: The argument from the command line
        :param param: uhhh.
        :param ctx: uhh
        :raises ArgumentTypeError: if any id is invalid.
        :return: A list of episode ids.
        """
        try:
            item_id = int(value)
            if not (item_id > 0 or item_id == -1):  # Must be positive or -1
                self.fail(f"{item_id} is not a valid episode ID")
        except ValueError:
            try:
                UUID(value)
            except ValueError:
                self.fail(f"{value} is not a valid uuid")
        return value


def get_all_episodes() -> Iterable[Episode]:
    """Retrieve all episodes from the server."""
    data = requests.get(
        f"{BASE_URL}/{FEED_ID}/episodes",
        headers=BEARER_TOKEN,
    )
    data.raise_for_status()

    return [Episode(**i) for i in data.json()]


def episode_info(episode_id: str) -> Optional[Episode]:
    """Retrieve all data for the specified episode, should one exist.

    :param episode_id: The ID of the episode to retrieve information for.
        Either an integer episode number,a UUID, or -1 which returns the latest
        episode.
    :raises ArgumentError: if the ``episode_id`` turns out to be invalid.
    :return: An `Episode` containing data for the ``episode_id``
    """
    response = requests.get(f"{BASE_URL}/{FEED_ID}/episode/{episode_id}")
    if response.status_code == 404:
        raise click.BadParameter(f"Episode {episode_id} was not found")
    return Episode(**response.json())


@click.group(context_settings={"max_content_width": 90})
def cli() -> None:
    """Remote control script for the snapcast podcast host."""
    pass


@cli.command(name="list")
@click.option(
    "--sort",
    help="sort results. default: pub_date",
    default="pub_date",
    type=click.Choice(['pub_date', 'id']),
)
@click.option("--find", help="filter output to results containing TEXT")
def list_(sort: str, find: Optional[str]) -> None:
    """Print a list of all episodes."""
    episodes = get_all_episodes()

    if find:
        episodes = filter(lambda x: find in x.title, episodes)

    lines = []
    width = get_terminal_size((0, 0)).columns
    for ep in sorted(episodes, key=lambda x: getattr(x, sort)):
        lines.append("│ ".join([
            f"{ep.id:3}",
            f"{ep.pub_date:%Y-%m-%d}",
            f"{ep.media_duration!s:>8}",
            f"{ep.media_size / 1000000:#6.2F} MB",
            f"{fwtruncate(ep.title, width - 38)}" if width else f"{ep.title}",
        ]))
    click.echo("\n".join(lines))


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("episode_id", required=True, type=EpisodeIdType())
def info(episode_id: str) -> None:
    """Fetch information about an episode."""
    if (episode := episode_info(episode_id)) is None:
        raise click.BadParameter(f"ID {episode_id} not found.")
    click.echo(pf(episode))


@cli.command(context_settings={'ignore_unknown_options': True})
@click.argument("episode_id", required=True, type=EpisodeIdType())
@click.argument("field", required=True, type=click.Choice(database_fields))
@click.argument("value", required=True)
def update(episode_id: str, field: str, value: str) -> None:
    """Update episode info in the remote host."""
    if (episode := episode_info(episode_id)) is None:
        raise click.BadParameter(f"ID {episode_id} not found.")
    episode_uuid = episode.uuid

    match field:
        case "media_duration":
            # Convert [[HH:]MM:]SS to integer seconds.
            value = sum(60 ** i * int(v) for i, v in
                        enumerate(value.split(":")[::-1]))
        case "pub_date":
            # Convert a local-tz "YYYY-MM-DD[ HH:MM]" to full spec UTC string.
            dt = datetime.fromisoformat(value)
            value = dt.astimezone(timezone.utc).isoformat()

    requests.patch(
        f"{BASE_URL}/{FEED_ID}/episode/{episode_uuid}",
        headers=BEARER_TOKEN,
        json={field: value},
    )


@cli.command()
@click.argument("episode_id", required=True, type=EpisodeIdType())
def delete(episode_id: str) -> None:
    """Delete episodes."""
    if (episode := episode_info(episode_id)) is None:
        raise click.BadParameter(f"ID {episode_id} not found.")

    requests.delete(
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

    click.echo(f"Episode entry #{episode_id} successfuly deleted")


if __name__ == '__main__':
    cli()
