"""The structural no-leakage guard on the launch path.

The web launch form is the only way an outsider's input enters a game. The
puppeteer notes ban a long list of words from player-visible strings; the cheap
way to hold that line forever is for the schema to admit no free string at all —
every string-ish field an Enum, everything else numbers and booleans. This test
walks the request model and fails the day someone adds a plain `str` field.
"""

import typing
from enum import Enum

from pydantic import BaseModel

from web.schemas import LaunchRequest


def flatten(annotation) -> list:
    """Every leaf type inside Optionals, Lists and Unions."""
    origin = typing.get_origin(annotation)
    if origin is None:
        return [annotation]
    leaves = []
    for arg in typing.get_args(annotation):
        if arg is type(None):
            continue
        leaves.extend(flatten(arg))
    return leaves


def string_fields(model: type[BaseModel], path: str = "") -> list[str]:
    offenders = []
    for name, field in model.model_fields.items():
        for leaf in flatten(field.annotation):
            if isinstance(leaf, type) and issubclass(leaf, BaseModel):
                offenders.extend(string_fields(leaf, f"{path}{name}."))
            elif isinstance(leaf, type) and issubclass(leaf, Enum):
                continue
            elif leaf is str:
                offenders.append(f"{path}{name}")
    return offenders


def test_no_field_of_the_launch_request_admits_free_text() -> None:
    assert string_fields(LaunchRequest) == [], (
        "a plain str field on LaunchRequest is a door from the browser into "
        "player-visible text; type it as an Enum or do not add it"
    )
