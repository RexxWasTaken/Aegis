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
        repository.save_ticket_transcript = AsyncMock()
        manager = TicketManager(Mock(), repository)
        manager.log_event = AsyncMock()
        manager.transcript_bytes = AsyncMock(return_value=b"complete transcript")
        channel = Mock(spec=discord.TextChannel)
        channel.delete = AsyncMock()
        staff = _member(50, role_ids=(99,))

        transcript = await manager.delete(ticket=ticket, channel=channel, actor=staff)

        self.assertEqual(transcript, b"complete transcript")
        repository.save_ticket_transcript.assert_awaited_once_with(
            ticket_id=ticket.ticket_id,
            transcript=b"complete transcript",
        )
        channel.delete.assert_awaited_once()
        repository.set_ticket_status.assert_awaited_once()
        self.assertEqual(repository.set_ticket_status.await_args.kwargs["status"], "closed")
        manager.log_event.assert_awaited_once()
        self.assertEqual(manager.log_event.await_args.kwargs["event"], "Deleted")
        self.assertEqual(
            manager.log_event.await_args.kwargs["transcript"],
            b"complete transcript",
        )

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

    async def test_open_ticket_creates_private_channel_and_prevents_duplicate(self) -> None:
        ticket = _ticket()
        repository = Mock()
        repository.get_ticket_config = AsyncMock(
            return_value=TicketConfig(10, 99, 40, None)
        )
        repository.get_open_ticket = AsyncMock(side_effect=[None, ticket])
        repository.create_ticket = AsyncMock(return_value=ticket)
        manager = TicketManager(Mock(), repository)
        manager.log_event = AsyncMock()

        creator = Mock(spec=discord.Member)
        creator.id = 30
        creator.mention = "<@30>"
        creator.display_name = "Ticket Creator"
        staff_role = Mock(spec=discord.Role)
        staff_role.id = 99
        category = Mock(spec=discord.CategoryChannel)
        bot_member = Mock(spec=discord.Member)
        default_role = Mock(spec=discord.Role)
        default_role.id = 0
        created_channel = Mock(spec=discord.TextChannel)
        created_channel.id = 20
        created_channel.delete = AsyncMock()
        existing_channel = Mock(spec=discord.TextChannel)
        existing_channel.mention = "#ticket-existing"
        guild = SimpleNamespace(
            id=10,
            default_role=default_role,
            me=bot_member,
            get_member=lambda member_id: bot_member if member_id == 1 else None,
            get_role=lambda role_id: staff_role if role_id == 99 else None,
            get_channel=lambda channel_id: (
                category if channel_id == 40 else existing_channel
            ),
            create_text_channel=AsyncMock(return_value=created_channel),
        )
        manager.bot = SimpleNamespace(user=SimpleNamespace(id=1))

        created, channel = await manager.open_ticket(
            guild=guild,
            creator=creator,
            category="General Support",
        )

        self.assertEqual(created, ticket)
        self.assertIs(channel, created_channel)
        overwrites = guild.create_text_channel.await_args.kwargs["overwrites"]
        self.assertFalse(overwrites[default_role].view_channel)
        self.assertTrue(overwrites[creator].view_channel)
        self.assertTrue(overwrites[staff_role].manage_messages)
        self.assertTrue(overwrites[bot_member].manage_channels)

        with self.assertRaisesRegex(TicketManagerError, "already have an open ticket"):
            await manager.open_ticket(
                guild=guild,
                creator=creator,
                category="General Support",
            )
        guild.create_text_channel.assert_awaited_once()

    async def test_close_reopen_and_claim_apply_permissions_and_persist_state(self) -> None:
        repository = Mock()
        repository.get_ticket_config = AsyncMock(
            return_value=TicketConfig(10, 99, None, None)
        )
        manager = TicketManager(Mock(), repository)
        manager.log_event = AsyncMock()
        manager.transcript_bytes = AsyncMock(return_value=b"transcript")
        creator = _member(30)
        staff = _member(50, role_ids=(99,))
        guild = SimpleNamespace(get_member=lambda member_id: creator if member_id == 30 else None)
        channel = Mock(spec=discord.TextChannel)
        channel.guild = guild
        overwrite = SimpleNamespace(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        )
        channel.overwrites_for.return_value = overwrite
        channel.set_permissions = AsyncMock()

        closed = _ticket(status="closed")
        repository.set_ticket_status = AsyncMock(return_value=closed)
        updated = await manager.close(
            ticket=_ticket(),
            channel=channel,
            actor=creator,
        )
        self.assertEqual(updated.status, "closed")
        self.assertFalse(overwrite.send_messages)
        repository.set_ticket_status.assert_awaited_once_with(
            channel_id=20,
            status="closed",
            closed_at=repository.set_ticket_status.await_args.kwargs["closed_at"],
        )

        claimed = _ticket(claimed_by=50)
        repository.claim_ticket = AsyncMock(return_value=claimed)
        self.assertEqual(
            (await manager.claim(_ticket(), staff)).claimed_by,
            staff.id,
        )

        opened = _ticket(status="open")
        repository.set_ticket_status = AsyncMock(return_value=opened)
        reopened = await manager.reopen(
            ticket=closed,
            channel=channel,
            actor=staff,
        )
        self.assertEqual(reopened.status, "open")
        self.assertTrue(overwrite.send_messages)
        repository.set_ticket_status.assert_awaited_once_with(
            channel_id=20,
            status="open",
            closed_at=None,
        )

    async def test_close_restores_original_permission_when_database_update_fails(self) -> None:
        repository = Mock()
        repository.get_ticket_config = AsyncMock(
            return_value=TicketConfig(10, 99, None, None)
        )
        repository.set_ticket_status = AsyncMock(
            side_effect=RuntimeError("database unavailable")
        )
        manager = TicketManager(Mock(), repository)
        creator = _member(30)
        guild = SimpleNamespace(get_member=lambda member_id: creator)
        channel = Mock(spec=discord.TextChannel)
        channel.guild = guild
        overwrite = SimpleNamespace(
            view_channel=True,
            send_messages=None,
            read_message_history=True,
        )
        channel.overwrites_for.return_value = overwrite
        channel.set_permissions = AsyncMock()

        with self.assertRaisesRegex(
            TicketManagerError,
            "previous channel permissions were restored",
        ):
            await manager.close(
                ticket=_ticket(),
                channel=channel,
                actor=creator,
            )

        self.assertEqual(channel.set_permissions.await_count, 2)
        self.assertIsNone(overwrite.send_messages)

    async def test_reopen_restores_closed_permissions_when_database_update_fails(self) -> None:
        repository = Mock()
        repository.get_ticket_config = AsyncMock(
            return_value=TicketConfig(10, 99, None, None)
        )
        repository.set_ticket_status = AsyncMock(side_effect=RuntimeError("db failed"))
        manager = TicketManager(Mock(), repository)
        manager.log_event = AsyncMock()
        staff = _member(50, role_ids=(99,))
        creator = _member(30)
        guild = SimpleNamespace(get_member=lambda member_id: creator)
        channel = Mock(spec=discord.TextChannel)
        channel.guild = guild
        overwrite = SimpleNamespace(
            view_channel=True,
            send_messages=False,
            read_message_history=True,
        )
        channel.overwrites_for.return_value = overwrite
        channel.set_permissions = AsyncMock()

        with self.assertRaisesRegex(TicketManagerError, "previous channel permissions"):
            await manager.reopen(
                ticket=_ticket(status="closed"),
                channel=channel,
                actor=staff,
            )

        self.assertFalse(overwrite.send_messages)
        self.assertEqual(channel.set_permissions.await_count, 2)
        manager.log_event.assert_not_awaited()

    async def test_failed_ticket_delete_restores_open_record_but_keeps_transcript(self) -> None:
        repository = Mock()
        repository.get_ticket_config = AsyncMock(
            return_value=TicketConfig(10, 99, None, None)
        )
        closed = _ticket(status="closed")
        repository.set_ticket_status = AsyncMock(
            side_effect=[closed, _ticket(status="open")]
        )
        repository.save_ticket_transcript = AsyncMock()
        manager = TicketManager(Mock(), repository)
        manager.transcript_bytes = AsyncMock(return_value=b"complete transcript")
        manager.log_event = AsyncMock()
        channel = Mock(spec=discord.TextChannel)
        channel.delete = AsyncMock(
            side_effect=discord.HTTPException(
                SimpleNamespace(status=500, reason="test failure"),
                "delete failed",
            )
        )

        with self.assertRaisesRegex(TicketManagerError, "open status and transcript"):
            await manager.delete(
                ticket=_ticket(),
                channel=channel,
                actor=_member(50, role_ids=(99,)),
            )

        repository.save_ticket_transcript.assert_awaited_once_with(
            ticket_id=17,
            transcript=b"complete transcript",
        )
        self.assertEqual(repository.set_ticket_status.await_count, 2)
        self.assertEqual(
            repository.set_ticket_status.await_args_list[1].kwargs["status"],
            "open",
        )
        manager.log_event.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
