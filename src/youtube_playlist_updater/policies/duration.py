from ..models import Assessment, Decision, ReviewOption, Video


class DurationPolicy:
    """Optional duration exclusion and human review, independent of a channel."""

    def __init__(self, targets: tuple[str, ...], minimum_seconds=0, review_max_seconds=0):
        self.targets = targets
        self.minimum_seconds = minimum_seconds
        self.review_max_seconds = review_max_seconds

    def episode_key(self, title: str, override_number=None):
        return None

    def demo_video(self):
        seconds = max(1, self.minimum_seconds)
        return Video("demo-duration", "Example video", "2026-10-07T18:00:00Z", seconds)

    def classify(self, video: Video) -> Assessment:
        if video.seconds < self.minimum_seconds:
            return Assessment("ignore", f"Duration below {self.minimum_seconds} seconds: excluded under the configured rule.", nature="short_by_duration")
        if self.review_max_seconds and video.seconds <= self.review_max_seconds:
            return Assessment("review", f"Duration in the configured review range ({self.minimum_seconds}–{self.review_max_seconds} seconds inclusive). Check whether this video belongs in the selection.")
        return Assessment("add", "Duration satisfies the configured automatic selection rule.", self.targets, "full_by_duration")

    def review_options(self, video: Video, assessment: Assessment) -> tuple[ReviewOption, ...]:
        return (
            ReviewOption("1", "Include this video → add to the configured playlists", Decision("add", self.targets, "full_video")),
            ReviewOption("2", "Exclude this video → ignore", Decision("ignore", nature="short_or_extract")),
        )
