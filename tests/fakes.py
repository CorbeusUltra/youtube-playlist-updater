from youtube_playlist_updater.models import Video
from youtube_playlist_updater.youtube import InsertResult, UnconfirmedAddition


def video(vid, title, seconds=1200, date="2026-10-07T18:00:00Z", channel="channel", broadcast="none"):
    return Video(vid, title, date, seconds, channel, broadcast)


class FakeYouTube:
    def __init__(self, profile, new=()):
        self.profile = profile
        self.base = video("base", "Previously selected upload", date="2026-07-01T18:00:00Z")
        self.metadata = {v.id: v for v in [self.base, *new]}
        self.playlists = {target.id: ["base"] for target in profile.targets}
        self.playlists["uploads"] = [v.id for v in new] + ["base"]
        self.calls = []
        self.fail_target = None
        self.fail_description = False
        self.stamps = []

    def channel(self, reference):
        return "channel", "uploads"

    def validate_targets(self, ids):
        return {key: key for key in ids}

    def videos(self, ids):
        return {vid: self.metadata[vid] for vid in ids if vid in self.metadata}

    def items(self, pid):
        return [{"video_id": vid, "title": self.metadata[vid].title if vid in self.metadata else "Unavailable", "published_at": self.metadata[vid].published_at if vid in self.metadata else "", "position": i, "item_id": f"item-{vid}"} for i, vid in enumerate(self.playlists[pid])]

    def add_to_playlist(self, target, v, position):
        self.calls.append((target.key, v.id, position))
        if target.key == self.fail_target:
            raise RuntimeError("Simulated network failure")
        self.playlists[target.id].insert(position, v.id)
        return InsertResult(True, True)

    def confirm_addition(self, target, v):
        existing = next((item for item in self.items(target.id) if item["video_id"] == v.id), None)
        if existing is None:
            raise UnconfirmedAddition("Simulated write still awaiting confirmation")
        return InsertResult(True, True, existing)

    def update_tracking(self, target, checked_at, *, changed=False):
        if self.fail_description:
            raise RuntimeError("Simulated description failure")
        self.stamps.append(target.id)
        self.last_stamp = (changed, checked_at)
        return changed
