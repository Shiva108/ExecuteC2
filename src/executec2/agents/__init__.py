"""Agent plugin loader for ExecuteC2."""

import importlib
import inspect
import logging

from executec2.agents.base import AgentPlugin

logger = logging.getLogger(__name__)

_registry: dict[str, type[AgentPlugin]] = {}


def load_agents(module_paths: list[str]) -> None:
    """Discover and register AgentPlugin subclasses from module paths."""
    for path in module_paths:
        try:
            mod = importlib.import_module(path)
            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if issubclass(obj, AgentPlugin) and obj is not AgentPlugin:
                    instance = obj()
                    info = instance.get_info()
                    agent_name = info.get("name", name.lower())
                    watermark = info.get("watermark", "")
                    _registry[agent_name] = obj
                    if watermark:
                        _registry[watermark] = obj
                    logger.info("Registered agent plugin: %s (watermark=%s)", name, watermark)
        except Exception:
            logger.exception("Failed to load agent module: %s", path)


def get_agent_class(name_or_watermark: str) -> type[AgentPlugin] | None:
    return _registry.get(name_or_watermark)


def list_agent_types() -> list[str]:
    """Return unique agent type names (excludes watermark aliases)."""
    seen = set()
    result = []
    for key, cls in _registry.items():
        if cls not in seen:
            seen.add(cls)
            result.append(key)
    return result
