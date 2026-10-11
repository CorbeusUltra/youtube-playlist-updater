"""Convert legacy state without network access or data deletion."""
from dataclasses import asdict
from copy import deepcopy

from .models import Profile, Video, date_key
from .storage import validate


def clock_seconds(value: str) -> int:
    try:
        parts = [int(piece) for piece in value.split(":")]
        if len(parts) not in {2, 3}:
            return 0
        result = 0
        for part in parts:
            result = result * 60 + part
        return result
    except (ValueError, AttributeError):
        return 0


def _record(video: Video, status: str, targets, completed, *, human=True, nature="existing_selection", number=None):
    return {"status": status, "targets": list(targets), "completed": list(completed), "human": human, "nature": nature, "episode_number": number, "video": asdict(video), "fingerprint": video.fingerprint}


def playlist_state(data: dict, profile: Profile) -> dict:
    if len(profile.targets) != 1:
        raise ValueError("Legacy mono-playlist state requires exactly one destination.")
    if data.get("playlist_id") != profile.targets[0].id:
        raise ValueError("The legacy state belongs to a different playlist.")
    decisions = {}
    for item in data.get("videos", []):
        video = Video(item["video_id"], item["title"], item.get("published_at") or "", clock_seconds(item.get("duration", "")), profile.channel)
        targets = (profile.targets[0].key,)
        decisions[video.id] = _record(video, "add", targets, targets)
    dates = [record["video"]["published_at"] for record in decisions.values() if record["video"]["published_at"]]
    if not dates:
        raise ValueError("The legacy state has no baseline date. Initialize this profile explicitly instead.")
    return {"version": 2, "profile": profile.key, "playlist_ids": profile.playlist_ids, "channel_id": profile.channel, "baseline": max(dates, key=date_key), "initialized": False, "decisions": decisions, "descriptions_pending": []}


def convert_state(data: dict, profile: Profile, channel_id: str) -> dict:
    if data.get("version") == 2:
        state = deepcopy(data)
        if state.get("profile") != profile.key:
            raise ValueError("The imported state belongs to a different profile.")
    elif data.get("version") == 1:
        importer = getattr(profile.policy, "import_legacy_state", None)
        if importer is None:
            raise ValueError("Unsupported legacy state version for these selection rules.")
        state = importer(data, profile)
    elif data.get("version") is None:
        state = playlist_state(data, profile)
        state["channel_id"] = channel_id
    else:
        raise ValueError("Unsupported state version.")
    if state.get("channel_id") != channel_id or state.get("playlist_ids") != profile.playlist_ids:
        raise ValueError("The imported state belongs to a different channel or set of playlists.")
    validate(state)
    return state
