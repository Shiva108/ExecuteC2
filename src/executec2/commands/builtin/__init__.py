"""Register all 19 built-in commands for the python agent type."""

from executec2.commands.registry import ArgDef, CommandDef, get_registry

_PYTHON_COMMANDS = [
    CommandDef(name="pwd",     description="Print working directory",      cmd_id=4,  args=[]),
    CommandDef(name="cd",      description="Change directory",              cmd_id=8,  args=[ArgDef("path", "string", True)]),
    CommandDef(name="cp",      description="Copy file",                    cmd_id=12, args=[ArgDef("src", "string", True), ArgDef("dst", "string", True)]),
    CommandDef(name="ls",      description="List directory",               cmd_id=14, args=[ArgDef("path", "string", False, ".")]),
    CommandDef(name="rm",      description="Remove file/directory",        cmd_id=17, args=[ArgDef("path", "string", True)]),
    CommandDef(name="mv",      description="Move/rename file",             cmd_id=18, args=[ArgDef("src", "string", True), ArgDef("dst", "string", True)]),
    CommandDef(name="config",  description="Update agent runtime config",  cmd_id=21, args=[ArgDef("sleep", "int", False), ArgDef("jitter", "int", False)]),
    CommandDef(name="whoami",  description="Get current user identity",    cmd_id=22, args=[]),
    CommandDef(name="cat",     description="Read file contents",           cmd_id=24, args=[ArgDef("path", "string", True)]),
    CommandDef(name="mkdir",   description="Create directory",             cmd_id=27, args=[ArgDef("path", "string", True)]),
    CommandDef(name="upload",  description="Upload file to target",        cmd_id=33, args=[ArgDef("path", "string", True), ArgDef("data", "file", True)]),
    CommandDef(name="download",description="Download file from target",    cmd_id=34, args=[ArgDef("path", "string", True)]),
    CommandDef(name="ps",      description="List running processes",       cmd_id=41, args=[]),
    CommandDef(name="kill",    description="Kill process by PID",          cmd_id=42, args=[ArgDef("pid", "int", True)]),
    CommandDef(name="exec",    description="Execute program",              cmd_id=43, args=[ArgDef("program", "string", True), ArgDef("args", "string", False)]),
    CommandDef(name="jobs",    description="List background jobs",         cmd_id=46, args=[]),
    CommandDef(name="jobkill", description="Kill background job",          cmd_id=47, args=[ArgDef("job_id", "string", True)]),
    CommandDef(name="shell",   description="Execute shell command",        cmd_id=50, args=[ArgDef("command", "string", True)]),
    CommandDef(name="exit",    description="Terminate agent",              cmd_id=99, args=[]),
]


def register_builtin_commands() -> None:
    """Register all built-in python agent commands into the global registry."""
    registry = get_registry()
    for cmd in _PYTHON_COMMANDS:
        registry.register("python", cmd)
