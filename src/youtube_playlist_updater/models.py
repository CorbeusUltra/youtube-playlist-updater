from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import unicodedata
from typing import Protocol


def normalized(title: str) -> str:
    title = unicodedata.normalize("NFD", title)
    title = "".join(c for c in title if unicodedata.category(c) not in {"Mn", "Cf"})
    return re.sub(r"\s+", " ", title.lower().replace("’", "'").replace("‘", "'"))


def date_key(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


@dataclass(frozen=True)
class Video:
    id: str
    title: str
    published_at: str
    seconds: int
    channel_id: str = ""
    broadcast: str = "none"

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"

    @property
    def duration(self) -> str:
        hours, rem = divmod(self.seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"

    @property
    def fingerprint(self) -> list:
        return [self.title, self.seconds, self.published_at, self.broadcast]


@dataclass(frozen=True)
class Assessment:
    status: str  # add, ignore, review, wait
    reason: str
    targets: tuple[str, ...] = ()
    nature: str = ""
    episode: tuple[str, int] | None = None


@dataclass(frozen=True)
class Decision:
    action: str  # add, ignore, later, quit
    targets: tuple[str, ...] = ()
    nature: str = ""
    episode_number: int | None = None


@dataclass(frozen=True)
class ReviewOption:
    key: str
    label: str
    decision: Decision
    needs_episode_number: bool = False


@dataclass(frozen=True)
class Target:
    key: str
    id: str
    label: str
    order: str = "published"  # published, episode
    youtube_sort: bool = True
    update_description: bool = False
    description_every_scan: bool = False
    description: str | None = None
    timezone: str = "Europe/Zurich"


class Policy(Protocol):
    def classify(self, video: Video) -> Assessment: ...
    def review_options(self, video: Video, assessment: Assessment) -> tuple[ReviewOption, ...]: ...
    def episode_key(self, title: str, override_number: int | None = None) -> tuple[str, int] | None: ...


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    channel: str
    targets: tuple[Target, ...]
    policy: Policy
    credential_store: str = "common"
    initialization: str | None = None
    start_date: str | None = None
    timezone: str = "UTC"

    @property
    def playlist_ids(self) -> dict[str, str]:
        return {target.key: target.id for target in self.targets}

    @property
    def labels(self) -> dict[str, str]:
        return {target.key: target.label for target in self.targets}


@dataclass(frozen=True)
class DeferredVideo:
    video: Video
    reason: str


@dataclass
class Report:
    added: list[tuple[Video, str, bool]] = field(default_factory=list)
    planned: list[tuple[Video, str]] = field(default_factory=list)
    pending: list[Video] = field(default_factory=list)
    waiting: int = 0
    waiting_details: list[DeferredVideo] = field(default_factory=list)
    preserved_count: int = 0
    archived_count: int = 0
    excluded: int = 0
    removed: int = 0
    errors: list[str] = field(default_factory=list)
    descriptions: list[str] = field(default_factory=list)
    updated_descriptions: set[str] = field(default_factory=set)
    youtube_sort: set[str] = field(default_factory=set)
    initialized: bool = False
    stopped: bool = False
    selection: dict | None = None
