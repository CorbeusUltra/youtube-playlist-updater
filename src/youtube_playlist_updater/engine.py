from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime, timezone
from pathlib import Path

from .initialization import initial_selection, outside_selection
from .models import Decision, DeferredVideo, Profile, Report, Target, Video, date_key
from .storage import save
from .youtube import UnconfirmedAddition, error_reason


def number_for(title: str, decision: dict | None, profile: Profile) -> int | None:
    if decision and decision.get("episode_number"):
        return decision["episode_number"]
    key = profile.policy.episode_key(title)
    return key[1] if key else None


def insertion_position(items: list[dict], video: Video, target: Target, profile: Profile, decisions: dict) -> int:
    number = number_for(video.title, decisions.get(video.id), profile)
    if target.order == "episode" and number is None:
        raise RuntimeError("An episode number is required to preserve this playlist ordering.")
    for index, item in enumerate(items):
        if target.order == "episode":
            other = number_for(item["title"], decisions.get(item["video_id"]), profile)
            if other is not None and other > number:
                return index
        elif item.get("published_at") and date_key(item["published_at"]) > date_key(video.published_at):
            return index
    return len(items)


def _record(video: Video, status: str, targets=(), nature="", human=False, completed=(), episode_number=None) -> dict:
    return {"status": status, "targets": list(targets), "nature": nature, "human": human, "completed": list(completed), "episode_number": episode_number, "video": asdict(video), "fingerprint": video.fingerprint}


def synchronize(service, profile: Profile, state: dict | None, state_path: Path, choose, *, dry_run=False, review_archives=False, review_video=None, on_added=None, on_read=None, choose_initialization=None) -> Report:
    """Shared engine for detection, decisions, routing, retries and reporting."""
    if dry_run:
        state = deepcopy(state)
    started_at = datetime.now(UTC).isoformat()
    channel_id, uploads_id = service.channel(profile.channel)
    service.validate_targets(profile.playlist_ids)
    items = {target.key: service.items(target.id) for target in profile.targets}
    if on_read:
        on_read("Reading channel uploads…")
    source = service.items(uploads_id)
    all_ids = [item["video_id"] for item in source]
    all_ids += [item["video_id"] for playlist in items.values() for item in playlist]
    if state:
        if state.get("profile") != profile.key or state.get("playlist_ids") != profile.playlist_ids or state.get("channel_id") != channel_id:
            raise RuntimeError("Configuration changed: this state belongs to a different channel or set of playlists.")
        all_ids += [vid for vid, record in state["decisions"].items() if record["status"] == "add"]
        for record in state["decisions"].values():
            if set(record.get("targets", [])) - set(profile.playlist_ids):
                raise RuntimeError("The state contains an unknown destination. No videos were added.")
    videos = service.videos(all_ids)
    report = Report()
    members = {key: {item["video_id"] for item in playlist} for key, playlist in items.items()}
    for playlist in items.values():
        for item in playlist:
            if item["video_id"] in videos:
                meta = videos[item["video_id"]]
                item.update(title=meta.title, published_at=meta.published_at)
    if on_read:
        on_read(None)
    if state is None:
        selection = initial_selection(profile, videos, members, channel_id, started_at, choose_initialization)
        state = {"version": 2, "profile": profile.key, "playlist_ids": profile.playlist_ids, "channel_id": channel_id, "baseline": selection["cutoff"] or "", "selection": selection, "initialized": False, "decisions": {}, "descriptions_pending": []}
    decisions = state["decisions"]
    if not state.get("initialized", True):
        # Reconcile the existing selection without applying the new rules retroactively.
        for vid, video in videos.items():
            present = tuple(key for key in members if vid in members[key])
            if present and vid not in decisions:
                decisions[vid] = _record(video, "add", present, "existing_selection", True, present)
            elif vid not in decisions and video.published_at and video.broadcast not in {"live", "upcoming"} and (
                outside_selection(video, state["selection"]) if "selection" in state
                else date_key(video.published_at) <= date_key(state["baseline"])
            ):
                decisions[vid] = _record(video, "archive", nature="before_initial_baseline")
        state["initialized"] = True
        report.initialized = True
        report.selection = state.get("selection")
        report.preserved_count = len(set().union(*members.values()))
        report.archived_count = sum(record["status"] == "archive" for record in decisions.values())

    def persist():
        if not dry_run:
            save(state_path, state)

    def complete(video, target, record, *, modified):
        if target.key not in record["completed"]:
            record["completed"].append(target.key)
        pending_writes = record.get("pending_writes", [])
        if target.key in pending_writes:
            pending_writes.remove(target.key)
        if not pending_writes:
            record.pop("pending_writes", None)
        if modified:
            report.added.append((video, target.key, record["human"]))
            state.setdefault("timestamps", {}).setdefault(target.key, {})["modified_at"] = datetime.now(UTC).isoformat()
            if target.update_description:
                pending = state.setdefault("descriptions_pending", [])
                if target.key not in pending:
                    pending.append(target.key)
        persist()
        if on_added and modified:
            on_added(video, target.key, record["human"])

    state["last_scan_at"] = datetime.now(UTC).isoformat()
    persist()
    if review_video and review_video not in videos:
        raise RuntimeError("This video is not accessible in this profile channel, playlists or decisions.")
    known_episodes = {}
    for playlist in items.values():
        for item in playlist:
            record = decisions.get(item["video_id"], {})
            key = profile.policy.episode_key(item["title"], record.get("episode_number"))
            if key:
                known_episodes.setdefault(key, set()).add(item["video_id"])
    source_ids = {item["video_id"] for item in source}
    for vid, record in decisions.items():
        if record["status"] == "add" and vid not in videos:
            missing = [key for key in record["targets"] if key not in record.get("completed", []) and vid not in members[key]]
            if missing:
                report.errors.append(f"{record.get('video', {}).get('title', vid)}: video unavailable; the requested addition is still pending.")
    for video in sorted(videos.values(), key=lambda v: (date_key(v.published_at), v.id)):
        prior = decisions.get(video.id)
        forced = video.id == review_video
        if prior and prior["status"] == "add" and not dry_run:
            for target in profile.targets:
                if target.key in prior.get("pending_writes", []) and video.id in members[target.key]:
                    complete(video, target, prior, modified=True)
        if prior and prior["status"] == "archive" and not review_archives and not forced:
            continue
        if prior and prior["status"] == "ignore" and not forced and (prior.get("human") or prior.get("fingerprint") == video.fingerprint):
            continue
        if prior and prior["status"] == "add" and not forced and all(key in prior.get("completed", []) or video.id in members[key] for key in prior["targets"]):
            # An already processed video is not a new release awaiting completion.
            for key in prior["targets"]:
                if video.id in members[key] and key not in prior["completed"]:
                    prior["completed"].append(key)
                    persist()
                elif video.id not in members[key]:
                    report.removed += 1
            continue
        if video.broadcast in {"live", "upcoming"} or not video.published_at or video.seconds <= 0:
            if video.broadcast == "upcoming":
                reason = "YouTube reports an upcoming premiere. It will be checked again on the next run."
            elif video.broadcast == "live":
                reason = "Live stream in progress: wait until it finishes before adding it."
            elif not video.published_at:
                reason = "YouTube does not provide a usable publication date yet."
            else:
                reason = "YouTube does not provide a usable duration yet. It will be checked again on the next run."
            report.waiting += 1
            report.waiting_details.append(DeferredVideo(video, reason))
            continue
        if "selection" in state and not forced and not review_archives and not (prior and prior["status"] == "add") and outside_selection(video, state["selection"]):
            decisions[video.id] = _record(video, "archive", nature="before_initial_baseline")
            persist()
            continue
        if prior and prior["status"] == "add" and not forced:
            record = prior
        else:
            if not forced and (video.id not in source_ids or video.channel_id != channel_id):
                continue
            assessment = profile.policy.classify(video)
            if forced:
                reason = "Review this video classification. Existing playlist entries will not be removed."
                if prior and prior.get("pending_writes"):
                    reason += " An earlier write is unconfirmed: check the playlist first. Choosing inclusion explicitly permits a new attempt if that entry is still absent."
                assessment = replace(assessment, status="review", reason=reason)
            if assessment.episode and known_episodes.get(assessment.episode, set()) - {video.id}:
                assessment = replace(assessment, status="review", reason="This episode number already exists: excerpt, reupload or another version?")
            if assessment.status == "wait":
                report.waiting += 1
                report.waiting_details.append(DeferredVideo(video, assessment.reason))
                continue
            if assessment.status == "review":
                decision = Decision("later") if dry_run else choose(video, assessment)
                if decision.action == "quit":
                    report.stopped = True
                    break
                if decision.action == "later":
                    report.pending.append(video)
                    # Deferring a review must not erase a previous approval.
                    if not prior or prior["status"] != "add":
                        decisions[video.id] = _record(video, "review")
                    persist()
                    continue
                if decision.action not in {"add", "ignore"} or set(decision.targets) - set(profile.playlist_ids):
                    raise RuntimeError("Invalid choice: no changes were made for this video.")
                if decision.action == "add" and not decision.targets:
                    raise RuntimeError("At least one destination is required to add a video.")
                record = _record(video, decision.action, decision.targets, decision.nature, True, prior.get("completed", []) if prior else (), decision.episode_number)
            else:
                record = _record(video, assessment.status, assessment.targets, assessment.nature)
            decisions[video.id] = record
            persist()
        if record["status"] == "ignore":
            report.excluded += 1
            continue
        key = profile.policy.episode_key(video.title, record.get("episode_number"))
        if key:
            known_episodes.setdefault(key, set()).add(video.id)
        for target in profile.targets:
            if target.key not in record["targets"]:
                continue
            if video.id in members[target.key]:
                if target.key not in record["completed"]:
                    record["completed"].append(target.key)
                    persist()
                continue
            if target.key in record["completed"]:
                # Respect manual removal after a confirmed addition.
                report.removed += 1
                continue
            reconciling = target.key in record.get("pending_writes", [])
            try:
                position = insertion_position(items[target.key], video, target, profile, decisions)
                if reconciling:
                    result = service.confirm_addition(target, video)
                    if dry_run:
                        complete(video, target, record, modified=False)
                        item = result.item or {"video_id": video.id, "title": video.title, "published_at": video.published_at, "position": position}
                        items[target.key].insert(item.get("position", position), item)
                        members[target.key].add(video.id)
                        continue  # Never propose another write for an uncertain attempt.
                elif dry_run:
                    report.planned.append((video, target.key))
                    members[target.key].add(video.id)
                    items[target.key].insert(position, {"video_id": video.id, "title": video.title, "published_at": video.published_at})
                    continue
                else:
                    # Persist before the write so a crash or lost response cannot cause a blind retry.
                    record.setdefault("pending_writes", []).append(target.key)
                    persist()
                    result = service.add_to_playlist(target, video, position)
                complete(video, target, record, modified=result.inserted)
                item = result.item or {"video_id": video.id, "title": video.title, "published_at": video.published_at, "position": position}
                items[target.key].insert(item.get("position", position), item)
                members[target.key].add(video.id)
                if not result.positioned:
                    report.youtube_sort.add(target.key)
            except Exception as exc:
                if not reconciling and not isinstance(exc, UnconfirmedAddition):
                    pending_writes = record.get("pending_writes", [])
                    if target.key in pending_writes:
                        pending_writes.remove(target.key)
                    if not pending_writes:
                        record.pop("pending_writes", None)
                report.errors.append(f"{video.title} → {target.label} : {error_reason(exc)}")
                persist()
                return report
    if not dry_run:
        if not report.errors and not report.stopped:
            for target in profile.targets:
                if target.update_description and target.description_every_scan:
                    pending = state.setdefault("descriptions_pending", [])
                    if target.key not in pending:
                        pending.append(target.key)
        # Refresh a single tracking line after a successful check or a real update.
        for key in list(state.get("descriptions_pending", [])):
            target = next((t for t in profile.targets if t.key == key), None)
            if not target or not target.update_description:
                continue
            try:
                changed = any(target_key == key for _, target_key, _ in report.added)
                updated = service.update_tracking(target, state["last_scan_at"], changed=changed)
                if updated:
                    report.updated_descriptions.add(key)
                state["descriptions_pending"].remove(key)
                report.descriptions.append(key)
                persist()
            except Exception as exc:
                report.errors.append(f"Description of {target.label} : {error_reason(exc)}")
        persist()
    return report
