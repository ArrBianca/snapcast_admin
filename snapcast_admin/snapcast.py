"""Functions that interface directly with the snapcast service."""

from dataclasses import KW_ONLY, dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
from urllib.parse import unquote

import requests
from b2sdk.exception import FileNotPresent

from .util import InvalidIdError, get_b2

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
    :raises InvalidIdError: if the ``episode_id`` turns out to be invalid.
    :return: An `Episode` containing data for the ``episode_id``
    """
    response = requests.get(f"{BASE_URL}/{FEED_ID}/episode/{episode_id}")
    if response.status_code == 404:
        raise InvalidIdError(f"Episode {episode_id} was not found.")
    return Episode(**response.json())


def update_episode(episode: Episode, field: str, value: str) -> None:
    """Update one attribute of an episode on the server.

    :param episode: The `Episode` to be updated.
    :param field: The field to be updated.
    :param value: The new value for the specified field.
    :return: None
    """
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
        f"{BASE_URL}/{FEED_ID}/episode/{episode.uuid}",
        headers=BEARER_TOKEN,
        json={field: value},
    )


def delete_episode(episode: Episode) -> None:
    """Delete an episode from the server and from backblaze."""
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
