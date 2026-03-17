"""Unit tests for the command registry and built-in commands."""

import pytest

from executec2.commands.builtin import register_builtin_commands
from executec2.commands.registry import ArgDef, CommandDef, CommandRegistry, get_registry

# ---------------------------------------------------------------------------
# CommandRegistry
# ---------------------------------------------------------------------------


def test_register_and_get():
    reg = CommandRegistry()
    cmd = CommandDef(name="shell", description="Execute shell", cmd_id=50,
                     args=[ArgDef("command", "string", True)])
    reg.register("python", cmd)
    assert reg.get("python", "shell") is cmd


def test_get_unknown_agent_type():
    reg = CommandRegistry()
    assert reg.get("nonexistent", "shell") is None


def test_get_unknown_command():
    reg = CommandRegistry()
    assert reg.get("python", "nonexistent") is None


def test_list_commands_empty():
    reg = CommandRegistry()
    assert reg.list_commands("python") == []


def test_list_commands_returns_all():
    reg = CommandRegistry()
    for i, name in enumerate(["pwd", "ls", "cat"]):
        reg.register("python", CommandDef(name=name, description=name, cmd_id=i))
    cmds = reg.list_commands("python")
    assert len(cmds) == 3
    names = {c.name for c in cmds}
    assert names == {"pwd", "ls", "cat"}


# ---------------------------------------------------------------------------
# Built-in commands registration
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fresh_registry(monkeypatch):
    """Isolate each test with a fresh registry instance."""
    from executec2.commands import registry as reg_mod
    fresh = CommandRegistry()
    monkeypatch.setattr(reg_mod, "_registry", fresh)
    yield fresh


def test_register_builtin_commands():
    register_builtin_commands()
    reg = get_registry()
    cmds = reg.list_commands("python")
    assert len(cmds) == 19


def test_all_19_command_names_present():
    register_builtin_commands()
    reg = get_registry()
    names = {c.name for c in reg.list_commands("python")}
    expected = {
        "pwd", "cd", "cp", "ls", "rm", "mv", "config", "whoami", "cat",
        "mkdir", "upload", "download", "ps", "kill", "exec", "jobs",
        "jobkill", "shell", "exit",
    }
    assert names == expected


def test_command_ids_match_spec():
    register_builtin_commands()
    reg = get_registry()
    assert reg.get("python", "shell").cmd_id == 50
    assert reg.get("python", "exit").cmd_id == 99
    assert reg.get("python", "pwd").cmd_id == 4
    assert reg.get("python", "upload").cmd_id == 33
    assert reg.get("python", "download").cmd_id == 34


def test_required_args_validated():
    register_builtin_commands()
    reg = get_registry()
    shell_cmd = reg.get("python", "shell")
    required_args = [a for a in shell_cmd.args if a.required]
    assert len(required_args) == 1
    assert required_args[0].name == "command"


def test_optional_args_have_defaults():
    register_builtin_commands()
    reg = get_registry()
    ls_cmd = reg.get("python", "ls")
    optional_args = [a for a in ls_cmd.args if not a.required]
    assert len(optional_args) == 1
    assert optional_args[0].default == "."


def test_no_args_commands():
    register_builtin_commands()
    reg = get_registry()
    for name in ["pwd", "whoami", "ps", "jobs", "exit"]:
        cmd = reg.get("python", name)
        assert cmd.args == [], f"{name} should have no args"


def test_two_arg_commands():
    register_builtin_commands()
    reg = get_registry()
    for name in ["cp", "mv"]:
        cmd = reg.get("python", name)
        assert len(cmd.args) == 2


def test_upload_has_file_type_arg():
    register_builtin_commands()
    reg = get_registry()
    upload = reg.get("python", "upload")
    arg_types = {a.name: a.type for a in upload.args}
    assert arg_types["data"] == "file"


def test_kill_has_int_pid_arg():
    register_builtin_commands()
    reg = get_registry()
    kill = reg.get("python", "kill")
    pid_arg = next(a for a in kill.args if a.name == "pid")
    assert pid_arg.type == "int"
    assert pid_arg.required is True
