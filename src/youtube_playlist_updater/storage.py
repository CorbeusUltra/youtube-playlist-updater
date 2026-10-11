from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
from .models import date_key


def validate(state: dict) -> None:
    if state.get("version") != 2 or not isinstance(state.get("decisions"), dict):
        raise ValueError("Invalid version or structure")
    for key in ("profile", "channel_id", "baseline"):
        if not isinstance(state.get(key), str):
            raise ValueError(f"Invalid {key}")
    if not isinstance(state.get("playlist_ids"), dict) or not state["playlist_ids"]:
        raise ValueError("Invalid playlist configuration")
    if "selection" in state:
        selection = state["selection"]
        if selection["mode"] not in {"future", "latest", "all", "date"} or type(selection["inclusive"]) is not bool:
            raise ValueError("Invalid selection boundary")
        if selection["mode"] == "all":
            if selection["cutoff"] is not None:
                raise ValueError("Invalid all-history selection")
        elif not isinstance(selection["cutoff"], str) or not selection["cutoff"]:
            raise ValueError("Missing selection boundary")
        else:
            date_key(selection["cutoff"])
    for decision in state["decisions"].values():
        if decision["status"] not in {"add", "ignore", "review", "archive"}:
            raise ValueError("Invalid decision")
        if not isinstance(decision.get("targets", []), list) or not isinstance(decision.get("completed", []), list):
            raise ValueError("Invalid destinations")
        if set(decision.get("targets", [])) - set(state["playlist_ids"]):
            raise ValueError("Unknown destination")
        pending = decision.get("pending_writes", [])
        if not isinstance(pending, list) or set(pending) - set(decision.get("targets", [])) or set(pending) & set(decision.get("completed", [])):
            raise ValueError("Invalid pending writes")
        if pending and decision["status"] != "add":
            raise ValueError("Only approved additions can have pending writes")


def load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        validate(state)
        return state
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise RuntimeError(f"Invalid local state : {path}. No videos were added. Restore the .previous.json backup if necessary.") from exc


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(".next.json")
    with staged.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    if path.exists():
        shutil.copy2(path, path.with_suffix(".previous.json"))
    staged.replace(path)


@contextmanager
def locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("An update is already running. Close this second instance.") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
