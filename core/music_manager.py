"""Startup and lifecycle management for the single Wavelink Lavalink node."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import wavelink

if TYPE_CHECKING:
    import discord


logger = logging.getLogger(__name__)


class MusicServiceUnavailable(RuntimeError):
    """Raised when a command needs Lavalink but no healthy node is available."""


class MusicManager:
    """Own one Lavalink node and expose its availability to the music cog."""

    def __init__(
        self,
        client: discord.Client,
        *,
        uri: str | None = None,
        password: str | None = None,
    ) -> None:
        self.client = client
        self.uri = (uri or os.environ.get("LAVALINK_URI") or "http://127.0.0.1:2333").rstrip("/")
        self.password = password if password is not None else os.environ.get("LAVALINK_PASSWORD", "")
        self.node: wavelink.Node | None = None
        self.last_error: str | None = None

    @property
    def available(self) -> bool:
        return (
            self.node is not None
            and self.node.status is wavelink.NodeStatus.CONNECTED
        )

    async def connect(self, *, attempts: int = 3, timeout: float = 10.0) -> bool:
        """Connect with bounded retries so Lavalink cannot block bot startup."""
        if not self.password.strip():
            self.last_error = "LAVALINK_PASSWORD is not configured."
            logger.error("%s Music commands will remain unavailable.", self.last_error)
            return False

        for attempt in range(1, attempts + 1):
            node = wavelink.Node(
                identifier="aegis-music",
                uri=self.uri,
                password=self.password,
                client=self.client,
                retries=3,
                resume_timeout=60,
            )
            try:
                nodes = await asyncio.wait_for(
                    wavelink.Pool.connect(nodes=[node], client=self.client),
                    timeout=timeout,
                )
            except (asyncio.TimeoutError, OSError, wavelink.LavalinkException) as exc:
                self.last_error = f"Lavalink connection attempt {attempt} failed: {exc}"
                logger.warning("%s", self.last_error)
                try:
                    await node.close()
                except Exception:
                    logger.debug("Could not close failed Lavalink node.", exc_info=True)
            except Exception as exc:
                self.last_error = f"Lavalink connection attempt {attempt} failed: {exc}"
                logger.exception("%s", self.last_error)
                try:
                    await node.close()
                except Exception:
                    logger.debug("Could not close failed Lavalink node.", exc_info=True)
            else:
                connected = nodes.get(node.identifier)
                if connected is not None and connected.status is wavelink.NodeStatus.CONNECTED:
                    self.node = connected
                    self.last_error = None
                    logger.info("Connected AEGIS music to Lavalink at %s.", self.uri)
                    return True

                self.last_error = (
                    "Lavalink did not accept a connection. Check the server URI, "
                    "password, and that the service is running."
                )
                logger.warning("%s", self.last_error)
                try:
                    await node.close()
                except Exception:
                    logger.debug("Could not close unavailable Lavalink node.", exc_info=True)

            if attempt < attempts:
                await asyncio.sleep(min(attempt * 2, 4))

        logger.error("Music is disabled for this session: %s", self.last_error)
        return False

    def require_node(self) -> wavelink.Node:
        """Return the connected node or give callers a useful configuration error."""
        if not self.available:
            detail = self.last_error or "No healthy Lavalink node is connected."
            raise MusicServiceUnavailable(detail)
        assert self.node is not None
        return self.node

    async def close(self) -> None:
        """Close Wavelink's node and its players during bot shutdown."""
        if self.node is None:
            return
        try:
            await self.node.close(eject=True)
        finally:
            self.node = None


def get_music_manager(client: object) -> MusicManager:
    """Fetch the manager installed by AegisBot.setup_hook."""
    manager = getattr(client, "music_manager", None)
    if not isinstance(manager, MusicManager):
        raise MusicServiceUnavailable("The AEGIS music service is not initialized.")
    manager.require_node()
    return manager
