"""Load an explicitly configured local policy module; nothing is auto-discovered."""
import hashlib
import importlib.util
import sys
from pathlib import Path


def load_policy_factories(config_path: Path, extension_path=None) -> dict:
    if extension_path is None:
        return {}
    if not isinstance(extension_path, str) or not extension_path.strip():
        raise ValueError("settings.policy_extension must be a Python file path.")
    path = Path(extension_path).expanduser()
    path = (config_path.parent / path).resolve() if not path.is_absolute() else path.resolve()
    if path.suffix != ".py" or not path.is_file():
        raise ValueError(f"Policy extension not found or not a Python file: {path}")
    module_name = "_playlist_local_" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        factories = getattr(module, "POLICY_FACTORIES", None)
        if not isinstance(factories, dict) or any(not isinstance(key, str) or not callable(factory) for key, factory in factories.items()):
            raise ValueError("Policy extensions must export a POLICY_FACTORIES mapping of names to factories.")
        if "duration" in factories:
            raise ValueError("A local extension cannot replace the built-in duration rules.")
        return dict(factories)
    finally:
        sys.modules.pop(module_name, None)
