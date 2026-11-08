"""Render actual discord.Embed payloads as a self-contained review page.

This is a design preview only. It does not connect to a Discord server,
register moderation commands, or perform moderation actions.
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path
from types import SimpleNamespace

import discord

from core.emoji_manager import EMOJI_IDS
from database.repositories.moderation import ModerationWarning, WarningStats
from embeds.moderation import (
    COMMAND_SPECS,
    confirmation_embed,
    success_embed,
    warning_history_embeds,
    warning_list_embed,
    warning_stats_embed,
)
from embeds.moderation_errors import missing_permissions_embed, wrong_usage_embed


CUSTOM_EMOJI_PATTERN = re.compile(r"<:([a-zA-Z0-9_]+):(\d+)>")
SAMPLE_USER_MENTION = "<@111111111111111111>"
SAMPLE_USER = SimpleNamespace(id=111111111111111111, mention=SAMPLE_USER_MENTION)
SAMPLE_WARNINGS = [
    ModerationWarning(
        warning_id=104,
        guild_id=1,
        target_id=SAMPLE_USER.id,
        moderator_id=222222222222222222,
        reason="Repeated spam",
        created_at="2026-01-01T00:00:00+00:00",
    ),
    ModerationWarning(
        warning_id=98,
        guild_id=1,
        target_id=SAMPLE_USER.id,
        moderator_id=333333333333333333,
        reason="Disruptive behavior",
        created_at="2025-12-15T00:00:00+00:00",
    ),
]
SAMPLE_STATS = WarningStats(
    total_warnings=12,
    members_warned=8,
    moderators_with_warnings=3,
)
SAMPLE_PURGE_COUNTS = {
    "purge": 50,
    "purgeuser": 25,
    "purgebots": 20,
    "purgehumans": 20,
    "purgelinks": 10,
}


class PreviewConfirmationView(discord.ui.View):
    """Actual discord.py button components, used only in the preview renderer."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Confirm", style=discord.ButtonStyle.success))
        self.add_item(discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary))


def render_text(value: str) -> str:
    """Escape embed text while retaining custom emoji as visible markup tokens."""
    pieces: list[str] = []
    offset = 0
    for match in CUSTOM_EMOJI_PATTERN.finditer(value):
        pieces.append(html.escape(value[offset:match.start()]))
        name, emoji_id = match.groups()
        pieces.append(
            '<span class="emoji-token" title="Custom emoji '
            + html.escape(name)
            + " · ID "
            + html.escape(emoji_id)
            + '">:'
            + html.escape(name)
            + ":</span>"
        )
        offset = match.end()
    pieces.append(html.escape(value[offset:]))
    rendered = "".join(pieces)
    return rendered.replace(html.escape(SAMPLE_USER_MENTION), "@Rexx")


def render_embed(embed: discord.Embed, label: str, view: discord.ui.View | None = None) -> str:
    """Render data serialized from a discord.Embed instance."""
    payload = embed.to_dict()
    color_value = payload.get("color", 0x5865F2)
    accent = f"#{color_value:06x}"
    title = render_text(payload.get("title", ""))
    description = render_text(payload.get("description", "")).replace("\n", "<br>")
    description_html = f'<div class="embed-description">{description}</div>' if description else ""
    buttons_html = ""
    if view is not None:
        buttons = []
        for child in view.children:
            if isinstance(child, discord.ui.Button):
                style = "primary" if child.style == discord.ButtonStyle.success else "secondary"
                buttons.append(
                    f'<button class="discord-button {style}" type="button">'
                    f"{html.escape(child.label or '')}</button>"
                )
        if buttons:
            buttons_html = '<div class="button-row">' + "".join(buttons) + "</div>"
    return (
        '<section class="case">'
        f'<div class="case-label">{html.escape(label)}</div>'
        '<div class="discord-message">'
        '<div class="avatar" aria-hidden="true">R</div>'
        '<div class="message-body">'
        '<div class="author-line"><strong>AEGIS</strong><span>APP</span></div>'
        f'<article class="embed-card" style="--embed-accent:{accent}">'
        f'<div class="embed-title">{title}</div>'
        f"{description_html}"
        "</article>"
        f"{buttons_html}"
        "</div></div></section>"
    )


def render_page() -> str:
    """Build a visual preview for all 45 commands and their required responses."""
    groups: list[str] = []
    confirmation_count = 0
    for name, spec in COMMAND_SPECS.items():
        if name == "warnings":
            success = warning_history_embeds(SAMPLE_USER, SAMPLE_WARNINGS)[0]
        elif name == "warnlist":
            success = warning_list_embed(
                SAMPLE_WARNINGS, total=12, page=1, page_size=8, target=SAMPLE_USER
            )
        elif name == "warnstats":
            success = warning_stats_embed(SAMPLE_STATS)
        else:
            success = success_embed(
                name,
                warning_id=104 if name in {"warn", "unwarn"} else None,
                count=(
                    2 if name == "clearwarnings" else SAMPLE_PURGE_COUNTS.get(name)
                ),
                target=(
                    SAMPLE_USER if name in {"clearwarnings", "purgeuser"} else None
                ),
            )
        cases = [
            render_embed(success, "Success"),
            render_embed(wrong_usage_embed(name), "Wrong usage"),
            render_embed(missing_permissions_embed(name), "Permission error"),
        ]
        if spec.confirmation_title is not None:
            cases.append(
                render_embed(
                    confirmation_embed(
                        name,
                        count=(
                            2 if name == "clearwarnings" else SAMPLE_PURGE_COUNTS.get(name)
                        ),
                        target=(
                            SAMPLE_USER
                            if name in {"clearwarnings", "purgeuser"}
                            else None
                        ),
                    ),
                    "Confirmation",
                    PreviewConfirmationView(),
                )
            )
            confirmation_count += 1
        groups.append(
            f'<details class="command" open><summary>a!{html.escape(name)}</summary>'
            '<div class="cases">'
            + "".join(cases)
            + "</div></details>"
        )

    known_emoji_count = len(EMOJI_IDS)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AEGIS moderation embed previews</title>
<style>
:root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #313338; color: #f2f3f5; }}
main {{ max-width: 1120px; margin: 0 auto; padding: 32px 20px 64px; }}
h1 {{ margin: 0 0 8px; font-size: 25px; }}
.intro {{ color: #b5bac1; margin: 0 0 24px; line-height: 1.5; }}
.summary {{ color: #dbdee1; font-size: 13px; margin-bottom: 20px; }}
.command {{ border-top: 1px solid #3f4147; padding: 12px 0; }}
.command summary {{ cursor: pointer; color: #f2f3f5; font-weight: 650; }}
.cases {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(280px,1fr)); gap: 14px; padding: 14px 0 5px; }}
.case-label {{ margin: 0 0 7px; color: #b5bac1; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }}
.discord-message {{ display: flex; gap: 12px; align-items: flex-start; }}
.avatar {{ width: 40px; height: 40px; flex: 0 0 40px; border-radius: 50%; background: #5865f2; display: grid; place-items: center; font-weight: 800; }}
.message-body {{ min-width: 0; flex: 1; }}
.author-line {{ display: flex; align-items: center; gap: 6px; height: 24px; margin-bottom: 5px; }}
.author-line strong {{ font-size: 14px; }}
.author-line span {{ background: #5865f2; color: #fff; border-radius: 3px; padding: 1px 4px; font-size: 9px; font-weight: 800; }}
.embed-card {{ max-width: 520px; background: #2b2d31; border-left: 4px solid var(--embed-accent); border-radius: 4px; padding: 12px 14px; }}
.embed-title {{ color: #f2f3f5; font-size: 15px; line-height: 1.35; font-weight: 650; overflow-wrap: anywhere; }}
.embed-description {{ color: #dbdee1; font-size: 14px; line-height: 1.45; margin-top: 7px; white-space: normal; overflow-wrap: anywhere; }}
.emoji-token {{ color: #c8c9ff; background: #3a3b66; border-radius: 4px; padding: 1px 4px; font-family: ui-monospace,monospace; font-size: 12px; white-space: nowrap; }}
.button-row {{ display: flex; gap: 8px; margin-top: 8px; }}
.discord-button {{ border: 0; border-radius: 3px; padding: 8px 14px; color: #fff; font-size: 14px; font-weight: 600; }}
.discord-button.primary {{ background: #248046; }}
.discord-button.secondary {{ background: #4e5058; }}
@media (max-width: 560px) {{ main {{ padding: 22px 14px 40px; }} .cases {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body><main>
<h1>AEGIS moderation embeds</h1>
<p class="intro">Visual review of serialized discord.py Embed objects. Custom emoji tokens are shown by name because their availability depends on the Discord server.</p>
<div class="summary">{len(COMMAND_SPECS)} unique commands · 3 response designs each · {confirmation_count} confirmation designs · {known_emoji_count} configured custom emojis</div>
{"".join(groups)}
</main></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="attached_assets/aegis_moderation_embed_previews.html",
        help="Path for the self-contained HTML preview",
    )
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_page(), encoding="utf-8")
    print(f"Wrote {len(COMMAND_SPECS)} command previews to {output}")


if __name__ == "__main__":
    main()
