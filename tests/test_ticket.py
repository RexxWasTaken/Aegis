from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from core.emoji_manager import emoji_markup
from core.ticket_manager import TicketManager, TicketManagerError
from cogs.ticket import TicketDeleteConfirmView, TicketPanelView, TicketIssueSelect
from database.repositories.community import TicketConfig, TicketRecord
from embeds.ticket import (
    TICKET_COLOR,
    ticket_delete_confirmation_embed,
    ticket_info_embed,
    ticket_panel_embed,
)


def _ticket(*, status: str = "open", claimed_by: int | None = None) -> TicketRecord:
    return TicketRecord(
        ticket_id=17,
        guild_id=10,
        channel_id=20,
        creator_id=30,
        category="General Support",
        status=status,
        claimed_by=claimed_by,
        created_at=datetime.now(timezone.utc).isoformat(),
        closed_at=None,
    )


def _member(member_id: int, *, role_ids: tuple[int, ...] = (), manage_guild: bool = False):
    return SimpleNamespace(
        id=member_id,
        mention=f"<@{member_id}>",
        roles=[SimpleNamespace(id=role_id) for role_id in role_ids],
        guild_permissions=SimpleNamespace(
            manage_guild=manage_guild,
            administrator=False,
        ),
    )


class TicketTests(unittest.IsolatedAsyncioTestCase):
    def test_panel_matches_required_copy_and_dropdown_has_descriptions(self) -> None:
        panel = ticket_panel_embed()
        self.assertEqual(panel.color, TICKET_COLOR)
        self.assertEqual(
            panel.description,
            "Make Ticket For Complains Here\n\n"
            "To create a ticket, select an issue from the dropdown below.\n\n"
            f"{emoji_markup('ticket')} AEGIS Support",
        )
        self.assertEqual(panel.fields, [])

        view = TicketPanelView(Mock())
        self.assertEqual(len(view.children), 1)
        select = view.children[0]
        self.assertIsInstance(select, TicketIssueSelect)
        self.assertEqual(select.placeholder, "What's The Issue?")
        self.assertEqual(
            [option.label for option in select.options],
            ["General Support", "Report a User", "Partnership", "Bug Report", "Other"],
        )
        self.assertTrue(all(option.description for option in select.options))
        self.assertTrue(all(option.emoji is not None for option in select.options))

    def test_ticket_info_and_delete_confirmation_are_clear_and_private_by_flow(self) -> None:
        ticket = _ticket(status="closed", claimed_by=40)
        info = ticket_info_embed(
            ticket,
            creator_name="<@30>",
            claimed_name="<@40>",
        )
        self.assertEqual(info.color, TICKET_COLOR)
        self.assertIn("Ticket #17", info.title)
        values = {field.name: field.value for field in info.fields}
        self.assertEqual(values["Status"], "Closed")
        self.assertEqual(values["Issue"], "General Support")
        self.assertEqual(values["Created by"], "<@30>")
        self.assertEqual(values["Claimed by"], "<@40>")

        confirmation = ticket_delete_confirmation_embed(ticket)
        self.assertIn("permanently deletes this ticket channel", confirmation.description)
        view = TicketDeleteConfirmView(Mock(), requester_id=40)
        self.assertEqual(
            [button.label for button in view.children],
            ["Confirm Delete", "Cancel"],
        )

    async def test_ticket_delete_requires_staff_and_keeps_event_history(self) -> None:
        ticket = _ticket()
        repository = Mock()
        repository.get_ticket_config = AsyncMock(
            return_value=TicketConfig(10, 99, None, None)
        )
        repository.set_ticket_status = AsyncMock()
        manager = TicketManager(Mock(), repository)
        manager.log_event = AsyncMock()
        channel = Mock(spec=discord.TextChannel)
        channel.delete = AsyncMock()
        staff = _member(50, role_ids=(99,))

        await manager.delete(ticket=ticket, channel=channel, actor=staff)

        channel.delete.assert_awaited_once()
        repository.set_ticket_status.assert_awaited_once()
        self.assertEqual(repository.set_ticket_status.await_args.kwargs["status"], "closed")
        manager.log_event.assert_awaited_once()
        self.assertEqual(manager.log_event.await_args.kwargs["event"], "Deleted")

    async def test_ticket_delete_rejects_non_staff_without_deleting_channel(self) -> None:
        repository = Mock()
        repository.get_ticket_config = AsyncMock(
            return_value=TicketConfig(10, 99, None, None)
        )
        manager = TicketManager(Mock(), repository)
        channel = Mock(spec=discord.TextChannel)
        channel.delete = AsyncMock()

        with self.assertRaises(TicketManagerError):
            await manager.delete(
                ticket=_ticket(),
                channel=channel,
                actor=_member(30),
            )

        channel.delete.assert_not_awaited()

    async def test_ticket_access_is_limited_to_creator_or_configured_staff(self) -> None:
        repository = Mock()
        repository.get_ticket_config = AsyncMock(
            return_value=TicketConfig(10, 99, None, None)
        )
        manager = TicketManager(Mock(), repository)
        ticket = _ticket()

        self.assertTrue(await manager.can_access(ticket, _member(30)))
        self.assertTrue(await manager.can_access(ticket, _member(50, role_ids=(99,))))
        self.assertFalse(await manager.can_access(ticket, _member(60)))


if __name__ == "__main__":
    unittest.main()
