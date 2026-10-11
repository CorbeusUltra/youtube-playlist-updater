import json
import re
from dataclasses import dataclass
from time import sleep
from zoneinfo import ZoneInfo

import httplib2
from googleapiclient.errors import HttpError

from .models import Target, Video, date_key

LAST_UPDATED_PREFIX = "🔄 Last updated:"
MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def error_reason(exc: Exception) -> str:
    if isinstance(exc, HttpError):
        try:
            return json.loads(exc.content)["error"]["errors"][0]["reason"]
        except (ValueError, KeyError, IndexError):
            return f"HTTP {exc.resp.status}"
    return str(exc) or type(exc).__name__


def duration_seconds(value: str) -> int:
    match = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        return 0
    days, hours, minutes, seconds = (int(n or 0) for n in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def normalize_description(value: str) -> str:
    """Normalize literal newline escapes found in legacy stored descriptions."""
    return value.replace("\\r\\n", "\n").replace("\\n", "\n")


@dataclass(frozen=True)
class InsertResult:
    inserted: bool
    positioned: bool
    item: dict | None = None


class UnconfirmedAddition(RuntimeError):
    """A write may have succeeded; only reconcile it until explicitly retried."""


class _ManualOrderingRequired(RuntimeError):
    """The API rejected the position; a numbered playlist must remain manual."""


class YouTube:
    """Data API operations without profile-specific title rules or thresholds."""
    def __init__(self, api):
        self.api = api
        self._owners = None
        self._videos: dict[str, Video] = {}

    def channel(self, reference: str) -> tuple[str, str]:
        criteria = {"id": reference} if reference.startswith("UC") else {"forHandle": reference.lstrip("@")}
        response = self.api.channels().list(part="contentDetails", **criteria).execute(num_retries=2)
        if not response.get("items"):
            raise RuntimeError(f"Channel {reference} not found.")
        item = response["items"][0]
        return item["id"], item["contentDetails"]["relatedPlaylists"]["uploads"]

    def validate_targets(self, ids: dict[str, str]) -> dict[str, str]:
        if self._owners is None:
            response = self.api.channels().list(part="id", mine=True).execute(num_retries=2)
            self._owners = {item["id"] for item in response.get("items", [])}
        response = self.api.playlists().list(part="snippet", id=",".join(ids.values())).execute(num_retries=2)
        targets = {item["id"]: item for item in response.get("items", [])}
        for name, playlist_id in ids.items():
            if playlist_id not in targets:
                raise RuntimeError(f"Playlist {name} not found or inaccessible ({playlist_id}). Check config.toml and the Google account.")
            if targets[playlist_id]["snippet"]["channelId"] not in self._owners:
                raise RuntimeError(f"The signed-in Google account does not own playlist {name}.")
        return {name: targets[pid]["snippet"]["title"] for name, pid in ids.items()}

    def items(self, playlist_id: str) -> list[dict]:
        result, page, visited = [], None, set()
        while True:
            response = self.api.playlistItems().list(part="snippet,contentDetails", playlistId=playlist_id, maxResults=50, pageToken=page).execute(num_retries=2)
            for item in response.get("items", []):
                result.append({"item_id": item["id"], "video_id": item["contentDetails"]["videoId"], "title": item["snippet"]["title"], "published_at": item["contentDetails"].get("videoPublishedAt", ""), "position": item["snippet"]["position"]})
            page = response.get("nextPageToken")
            if not page:
                return result
            if page in visited:
                raise RuntimeError("YouTube repeated a result page. Reading stopped to avoid an incomplete result.")
            visited.add(page)

    def videos(self, ids: list[str]) -> dict[str, Video]:
        unique = list(dict.fromkeys(ids))
        missing = [vid for vid in unique if vid not in self._videos]
        for offset in range(0, len(missing), 50):
            response = self.api.videos().list(part="snippet,contentDetails,status", id=",".join(missing[offset:offset + 50])).execute(num_retries=2)
            for item in response.get("items", []):
                snippet = item["snippet"]
                self._videos[item["id"]] = Video(item["id"], snippet["title"], snippet.get("publishedAt", ""), duration_seconds(item["contentDetails"].get("duration", "")), snippet["channelId"], snippet.get("liveBroadcastContent", "none"))
        return {vid: self._videos[vid] for vid in unique if vid in self._videos}

    def confirm_addition(self, target: Target, video: Video, *, positioned=True) -> InsertResult:
        """Bounded read-only reconciliation; never repeat an uncertain write."""
        last_error = None
        for delay in (0, 0.5, 1, 2):
            if delay:
                sleep(delay)
            try:
                existing = next((item for item in self.items(target.id) if item["video_id"] == video.id), None)
                if existing is not None:
                    return InsertResult(True, positioned, existing)
            except Exception as exc:
                last_error = exc
        message = "Addition still awaiting confirmation. No further insertion was sent. Run again to reconcile the earlier request."
        if last_error:
            message += f" Read error: {error_reason(last_error)}."
        raise UnconfirmedAddition(message)

    @staticmethod
    def _insert_receipt(response, target: Target, video: Video, position: int) -> dict | None:
        if not isinstance(response, dict) or not isinstance(response.get("id"), str) or not response["id"]:
            return None
        snippet = response.get("snippet", {})
        if not isinstance(snippet, dict) or snippet.get("playlistId") != target.id:
            return None
        resource = snippet.get("resourceId", {})
        if not isinstance(resource, dict) or resource.get("videoId") != video.id or resource.get("kind") != "youtube#video":
            return None
        actual_position = snippet.get("position", position)
        if type(actual_position) is not int or actual_position < 0:
            return None
        return {"item_id": response["id"], "video_id": video.id, "title": video.title,
                "published_at": video.published_at, "position": actual_position}

    def add_to_playlist(self, target: Target, video: Video, position: int) -> InsertResult:
        """Use the insertion receipt, or reconcile a lost response without another write."""
        existing = next((item for item in self.items(target.id) if item["video_id"] == video.id), None)
        if existing is not None:
            return InsertResult(False, True, existing)
        snippet = {"playlistId": target.id, "position": position, "resourceId": {"kind": "youtube#video", "videoId": video.id}}
        positioned = True
        try:
            try:
                response = self.api.playlistItems().insert(part="id,snippet", body={"snippet": snippet}).execute(num_retries=0)
            except HttpError as exc:
                if error_reason(exc) != "manualSortRequired":
                    raise
                if not target.youtube_sort:
                    raise _ManualOrderingRequired(f"Select Manual ordering in YouTube to preserve the order of {target.label}.") from exc
                snippet.pop("position")
                positioned = False
                response = self.api.playlistItems().insert(part="id,snippet", body={"snippet": snippet}).execute(num_retries=0)
        except _ManualOrderingRequired:
            raise
        except HttpError as exc:
            if 400 <= exc.resp.status < 500:
                raise  # A definite rejection can be retried after its cause is resolved.
            return self.confirm_addition(target, video, positioned=positioned)
        except Exception:
            return self.confirm_addition(target, video, positioned=positioned)
        receipt = self._insert_receipt(response, target, video, position)
        if receipt is not None:
            return InsertResult(True, positioned, receipt)
        return self.confirm_addition(target, video, positioned=positioned)

    def update_tracking(self, target: Target, checked_at: str, *, changed: bool = False) -> bool:
        """Write one tracking line; timestamp-only refreshes count as checks."""
        response = self.api.playlists().list(part="snippet", id=target.id).execute(num_retries=2)
        if not response.get("items"):
            raise RuntimeError("Playlist not found while updating its description.")
        original = response["items"][0]["snippet"]
        snippet = {key: original[key] for key in ("title", "description", "tags", "defaultLanguage") if key in original}
        prefixes = (LAST_UPDATED_PREFIX, "Last modified on:", "Last checked on:", "Last updated on:", "Last checked/updated on:")
        previous_body = "\n".join(line for line in normalize_description(original.get("description", "")).splitlines() if not line.startswith(prefixes)).strip()
        body = target.description.strip() if target.description is not None else previous_body
        updated = changed or body != previous_body
        when = date_key(checked_at).astimezone(ZoneInfo(target.timezone))
        formatted = f"{when.day} {MONTHS_EN[when.month - 1]} {when.year} at {when:%H:%M %Z}"
        marker = f"Last {'updated' if updated else 'checked'} on: {formatted}"
        snippet["description"] = f"{body}\n\n{marker}" if body else marker
        self.api.playlists().update(part="snippet", body={"id": target.id, "snippet": snippet}).execute(num_retries=0)
        return updated
