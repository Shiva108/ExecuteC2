"""Command registry for ExecuteC2."""

from dataclasses import dataclass, field


@dataclass
class ArgDef:
    name: str
    type: str  # "string" | "int" | "file"
    required: bool
    default: object = None


@dataclass
class CommandDef:
    name: str
    description: str
    cmd_id: int
    args: list[ArgDef] = field(default_factory=list)


class CommandRegistry:
    """Maps (agent_type, command_name) -> CommandDef."""

    def __init__(self):
        self._commands: dict[str, dict[str, CommandDef]] = {}

    def register(self, agent_type: str, cmd: CommandDef) -> None:
        self._commands.setdefault(agent_type, {})[cmd.name] = cmd

    def get(self, agent_type: str, name: str) -> CommandDef | None:
        return self._commands.get(agent_type, {}).get(name)

    def list_commands(self, agent_type: str) -> list[CommandDef]:
        return list(self._commands.get(agent_type, {}).values())


# Global registry instance
_registry = CommandRegistry()


def get_registry() -> CommandRegistry:
    return _registry
