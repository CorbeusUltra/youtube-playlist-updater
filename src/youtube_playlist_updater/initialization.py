"""Explicit initial selection limits, stored once and reused on later scans."""
from datetime import datetime, time, timezone, UTC
from zoneinfo import ZoneInfo

from .config import calendar_date
from .models import date_key


def initial_selection(profile, videos, members, channel_id, started_at, choose=None):
    dates = [v.published_at for vid, v in videos.items()
             if v.channel_id == channel_id and any(vid in ids for ids in members.values()) and v.published_at]
    mode, start_date = profile.initialization, profile.start_date
    if mode is None or (mode == "latest" and not dates and choose is not None):
        if choose is None:
            raise RuntimeError("Choose an initialization mode in config.toml before a non-interactive first run (future, latest, all or date).")
        mode, start_date = choose(bool(dates))
    if mode == "future":
        return {"mode": mode, "cutoff": started_at, "inclusive": True}
    if mode == "latest":
        if not dates:
            raise RuntimeError("No dated selection from the source channel is available. Choose future, all or date initialization.")
        return {"mode": mode, "cutoff": max(dates, key=date_key), "inclusive": False}
    if mode == "all":
        return {"mode": mode, "cutoff": None, "inclusive": True}
    if mode == "date":
        day = datetime.fromisoformat(calendar_date(start_date)).date()
        cutoff = datetime.combine(day, time.min, ZoneInfo(profile.timezone)).astimezone(UTC)
        return {"mode": mode, "cutoff": cutoff.isoformat(), "inclusive": True}
    raise ValueError("Invalid initialization mode.")


def outside_selection(video, selection):
    cutoff = selection.get("cutoff")
    if not cutoff or not video.published_at:
        return False
    published, boundary = date_key(video.published_at), date_key(cutoff)
    return published < boundary if selection["inclusive"] else published <= boundary
