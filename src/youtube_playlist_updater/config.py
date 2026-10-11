import re
import tomllib
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Profile, Target
from .extensions import load_policy_factories
from .policies.duration import DurationPolicy

MODES = {"future", "latest", "all", "date"}


def name(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
        raise ValueError(f"Invalid {label}: use letters, digits, underscores or hyphens.")
    return value


def integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer of at least {minimum}.")
    return value


def boolean(value, label):
    if type(value) is not bool:
        raise ValueError(f"{label} must be true or false.")
    return value


def label(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Labels must be nonempty strings.")
    return value


def calendar_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("start_date must use YYYY-MM-DD (a quoted string).")
    date.fromisoformat(value)
    return value


def load_config(path: Path) -> tuple[dict[str, Profile], dict]:
    # Accept a directory for callers of the previous API.
    path = path / "config.toml" if path.is_dir() else path
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Configuration not found: {path}. Copy config.example.toml to config.toml and edit it, or use --config PATH.") from exc
    settings = config.get("settings", {})
    timezone = settings.get("timezone", "UTC")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
        raise ValueError("settings.timezone must be a valid IANA time zone.") from exc
    auth = config.get("auth", {})
    port = integer(auth.get("oauth_port", 0), "oauth_port")
    if port > 65535:
        raise ValueError("oauth_port must not exceed 65535.")
    factories = load_policy_factories(path, settings.get("policy_extension"))
    values = config.get("profiles", {})
    if not values:
        raise ValueError("Configure at least one profile.")
    profiles, seen_ids = {}, set()
    for key, value in values.items():
        name(key, "profile key")
        if key in {"all", "quit"}:
            raise ValueError(f"Profile key {key!r} is reserved by the selector.")
        policy_name = value.get("policy", "duration")
        if not isinstance(policy_name, str) or policy_name not in {"duration", *factories}:
            raise ValueError(f"Unknown policy {policy_name!r} for profile {key}. Use the built-in duration rules or configure a local extension.")
        channel = value.get("channel", "")
        if not isinstance(channel, str) or not channel or not (channel.startswith("UC") or (channel.startswith("@") and len(channel) > 1)):
            raise ValueError(f"Profile {key}: channel must be a UC channel ID or an @handle.")
        store = name(value.get("credential_store", "common"), "credential store")
        mode = value.get("initialization")
        if mode is not None and mode not in MODES:
            raise ValueError(f"Profile {key}: initialization must be future, latest, all or date.")
        start_date = value.get("start_date")
        if mode == "date":
            calendar_date(start_date)
        elif start_date is not None:
            raise ValueError("start_date requires initialization = 'date'.")
        targets = []
        for target_key, data in value.get("playlists", {}).items():
            name(target_key, "destination key")
            playlist_id = data.get("id")
            if not isinstance(playlist_id, str) or not playlist_id.startswith("PL") or playlist_id in seen_ids:
                raise ValueError("Invalid or duplicate playlist ID.")
            seen_ids.add(playlist_id)
            order = data.get("order", "published")
            if order not in {"published", "episode"} or (order == "episode" and policy_name == "duration"):
                raise ValueError("Duration rules require publication ordering.")
            youtube_sort = boolean(data.get("youtube_sort", order != "episode"), "youtube_sort")
            if order == "episode" and youtube_sort:
                raise ValueError("Episode ordering requires youtube_sort = false.")
            description = data.get("description")
            if description is not None and not isinstance(description, str):
                raise ValueError("description must be a string.")
            targets.append(Target(target_key, playlist_id, label(data.get("label", target_key)), order, youtube_sort,
                                  boolean(data.get("update_description", False), "update_description"),
                                  boolean(data.get("description_every_scan", False), "description_every_scan"), description, timezone))
        if not targets:
            raise ValueError(f"Profile {key}: configure at least one destination playlist.")
        if policy_name in factories:
            policy = factories[policy_name](value, tuple(t.key for t in targets))
            if any(not callable(getattr(policy, method, None)) for method in ("classify", "review_options", "episode_key", "demo_video")):
                raise ValueError(f"Policy extension {policy_name!r} does not implement the required methods.")
            if any(t.order == "episode" for t in targets) and not getattr(policy, "supports_episode_ordering", False):
                raise ValueError("This local policy does not support episode ordering.")
        else:
            lower = integer(value.get("minimum_seconds", value.get("review_min_seconds", 0)), "minimum_seconds")
            upper = integer(value.get("review_max_seconds", 0), "review_max_seconds")
            if upper and upper < lower:
                raise ValueError("review_max_seconds must be zero (disabled) or at least minimum_seconds.")
            policy = DurationPolicy(tuple(t.key for t in targets), lower, upper)
        profiles[key] = Profile(key, label(value.get("label", key)), channel, tuple(targets), policy, store, mode, start_date, timezone)
    return profiles, auth
