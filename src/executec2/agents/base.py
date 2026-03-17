"""AgentPlugin ABC — base class for all agent type plugins."""

from abc import ABC, abstractmethod


class AgentPlugin(ABC):
    """Base class for all agent type plugins."""

    @abstractmethod
    def get_info(self) -> dict:
        """Return agent type metadata: name, watermark, compatible_listeners."""
        ...

    @abstractmethod
    def parse_beat(self, beat_data: bytes) -> dict:
        """Parse a registration beat from an agent. Returns agent field dict."""
        ...

    @abstractmethod
    def build_task(self, command_name: str, args: dict) -> dict:
        """Build a task payload: {type, cmd, args}."""
        ...

    @abstractmethod
    def process_response(self, task_id: str, response: dict) -> dict:
        """Process a task response. Returns {message_type, message, clear_text, completed}."""
        ...

    @abstractmethod
    def get_commands(self) -> list[dict]:
        """Return list of command definition dicts."""
        ...
