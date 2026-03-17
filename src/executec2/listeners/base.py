"""ListenerPlugin ABC — base class for all listener plugins."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from executec2.server.teamserver import TeamserverInterface


class ListenerPlugin(ABC):
    """Base class for all listener plugins."""

    @abstractmethod
    async def start(self, config: dict, teamserver: "TeamserverInterface") -> None:
        """Start the listener with the given configuration."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the listener and release all resources."""
        ...

    @abstractmethod
    async def pause(self) -> None:
        """Pause: accept connections but do not dequeue tasks."""
        ...

    @abstractmethod
    async def resume(self) -> None:
        """Resume a paused listener."""
        ...

    @abstractmethod
    def validate_config(self, config: dict) -> dict:
        """Validate and normalize config. Raises ValueError on invalid."""
        ...

    @abstractmethod
    def get_info(self) -> dict:
        """Return listener metadata: name, type, protocol."""
        ...
