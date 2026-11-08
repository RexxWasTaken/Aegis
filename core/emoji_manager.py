"""Central custom emoji catalog for the AEGIS moderation preview."""

from __future__ import annotations

from typing import Final


EMOJI_IDS: Final[dict[str, str]] = {
    "success": "1518658821650776225",
    "moderation": "1518658819545239683",
    "arrow": "1518658814822580234",
    "warning": "1518658812507328642",
    "delete": "1518658746438516787",
    "error": "1518668784519352390",
    "wrong": "1518693518829158501",
    "security": "1518658827954815097",
    "antinuke": "1518658825803010269",
    "folder": "1518658824003649556",
    "home": "1518658383601996039",
    "config": "1518667380400591030",
    "owner": "1518658844572651593",
    "developer": "1518658846854353112",
    "economy": "1518658840529342694",
    "media": "1518658838427861164",
    "fun": "1518658836045631799",
    "voice": "1518658834074308790",
    "ticket": "1518658831360589875",
    "welcomer": "1518658829779206335",
    "dnd": "1519408422280233100",
    "idle": "1519408420103520437",
    "offline": "1519408415980650526",
    "online": "1519408417935069324",
    "favorite": "1519285891187736659",
    "mute": "1519285710954430574",
    "queue": "1519285708798296144",
    "shuffle": "1519285706831429703",
    "volume": "1519285704910311555",
    "previous": "1519079339604578355",
    "next": "1519079337238990868",
    "pause": "1519079335380652052",
    "repeat": "1519079333358993560",
    "stop": "1519079331606040797",
    "play": "1519079329475199036",
    "larrow": "1518894588830552085",
    "giveaway": "1518667382581760110",
    "music": "1518660066113359884",
    "utility": "1518659768036757684",
    "ai": "1518658842177699851",
}


def emoji_markup(name: str) -> str:
    """Return Discord's custom emoji markup, or an empty string if unknown."""
    emoji_id = EMOJI_IDS.get(name)
    if emoji_id is None:
        return ""
    return f"<:{name}:{emoji_id}>"
