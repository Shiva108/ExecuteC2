"""Listener plugin loader for ExecuteC2."""

import importlib
import inspect
import logging

from executec2.listeners.base import ListenerPlugin

logger = logging.getLogger(__name__)

_registry: dict[str, type[ListenerPlugin]] = {}


def load_listeners(module_paths: list[str]) -> None:
    """Discover and register ListenerPlugin subclasses from module paths."""
    for path in module_paths:
        try:
            mod = importlib.import_module(path)
            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if issubclass(obj, ListenerPlugin) and obj is not ListenerPlugin:
                    info = obj().get_info()
                    plugin_type = info.get("type", name.lower())
                    _registry[plugin_type] = obj
                    logger.info("Registered listener plugin: %s (%s)", name, plugin_type)
        except Exception:
            logger.exception("Failed to load listener module: %s", path)


def get_listener_class(type_name: str) -> type[ListenerPlugin] | None:
    return _registry.get(type_name)


def list_listener_types() -> list[str]:
    return list(_registry.keys())
