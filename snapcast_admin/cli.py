from pprint import pformat as pf
from shutil import get_terminal_size
from typing import Optional

import click

from .snapcast import (
    Episode,
    database_fields,
    delete_episode,
    episode_info,
    get_all_episodes,
    update_episode,
)
from .util import fwtruncate


class EpisodeType(click.ParamType):  # noqa: D101
    name = "episode"

    def convert(
            self, value: str,
            param: Optional[click.Parameter],
            ctx: Optional[click.Context],
    ) -> Episode:
        """Convert an episode ID from the cli to an Episode object."""
        if (episode := episode_info(value)) is not None:
            return episode
        # `fail` raises an exception so None won't ever be returned here
        self.fail(f"{value} is not a valid episode ID.")  # noqa: RET503


@click.group(context_settings={"max_content_width": 90})
def cli() -> None:
    """Remote control script for the snapcast podcast host."""
    pass


@cli.command(name="list")
@click.option(
    "--sort",
    help="sort results. default: pub_date",
    default="pub_date",
    type=click.Choice(["pub_date", "id"]),
)
@click.option("--find", help="filter output to results containing TEXT")
def handle_list(sort: str, find: Optional[str]) -> None:
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
@click.argument("episode", required=True, type=EpisodeType())
def info(episode: Episode) -> None:
    """Fetch information about an episode."""
    click.echo(pf(episode))


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("episode", required=True, type=EpisodeType())
@click.argument("field", required=True, type=click.Choice(database_fields))
@click.argument("value", required=True)
def update(episode: Episode, field: str, value: str) -> None:
    """Update episode info in the remote host."""
    update_episode(episode, field, value)


@cli.command()
@click.argument("episode", required=True, type=EpisodeType())
def delete(episode: Episode) -> None:
    """Delete episodes."""
    delete_episode(episode)


if __name__ == "__main__":
    cli()
