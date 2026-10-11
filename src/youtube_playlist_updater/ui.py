import webbrowser
from dataclasses import replace

import questionary
from rich.panel import Panel
from rich.prompt import IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from .config import calendar_date
from .models import Decision, Profile, Report


def select_option(title, options, default):
    """Shared arrow-key selector for every finite-choice menu."""
    answer = questionary.select(
        title,
        choices=[questionary.Choice(label, value=value) for value, label in options],
        default=default,
        qmark="",
        pointer="❯",
        use_shortcuts=False,
        use_arrow_keys=True,
        use_jk_keys=False,
        use_emacs_keys=False,
        instruction="↑/↓ move · Enter select · Ctrl+C cancel",
        style=questionary.Style([
            ("question", "bold"),
            ("pointer", "fg:#5fd7ff bold noreverse"),
            ("highlighted", "fg:#5fd7ff bold noreverse"),
            # The default choice inherits prompt_toolkit's reversed selected style.
            ("selected", "noreverse"),
            ("answer", "fg:#5fd7ff bold"),
            ("instruction", "fg:#888888"),
        ]),
    ).unsafe_ask()
    if answer is None:
        raise KeyboardInterrupt
    return answer


def select_profiles(console, profiles: dict[str, Profile]) -> list[Profile]:
    options = [(key, f"{profile.label} — {len(profile.targets)} playlist{'s' if len(profile.targets) > 1 else ''}") for key, profile in profiles.items()]
    options += [("all", "All configured profiles"), ("quit", "Quit")]
    selected = select_option("Which playlists would you like to update?", options, "all")
    if selected == "quit":
        return []
    return list(profiles.values()) if selected == "all" else [profiles[selected]]


def initialization_chooser(console, profile):
    def choose(latest_available):
        console.print(Text("First run: existing playlist entries will be preserved. Choose which other uploads to process."))
        options = [("future", "Only future publications — start now"), ("all", "All available uploads — include the history"), ("date", "Publications from a chosen date, inclusive")]
        if latest_available:
            options.insert(1, ("latest", "Resume after the newest selected video from this channel"))
        else:
            console.print("No dated selection from this channel: resuming after a selected video is unavailable.")
        mode = select_option("Where should the selection start?", options, "future")
        start_date = None
        if mode == "date":
            while True:
                start_date = Prompt.ask(f"Start date (YYYY-MM-DD, inclusive, {profile.timezone})", console=console)
                try:
                    calendar_date(start_date)
                    break
                except ValueError as exc:
                    console.print(Text(str(exc), style="yellow"))
        return mode, start_date
    return choose



def video_details(video, reason=None):
    details = Text(f"{video.title}\n\nDuration: {video.duration} · Published: {video.published_at[:10]}\n")
    details.append(video.url, style=f"link {video.url} underline cyan")
    if reason:
        details.append(f"\n\n{reason}")
    return details


def chooser(console, profile: Profile, interactive=True):
    """Shared presentation; classification options come from the profile policy."""
    def choose(video, assessment):
        if not interactive:
            return Decision("later")
        console.print(Panel(video_details(video, assessment.reason), title="Video review", border_style="yellow"))
        options = profile.policy.review_options(video, assessment)
        choices = [(option.key, option.label) for option in options]
        choices += [
            ("4", "Decide later — this video will be offered again"),
            ("o", "Open the video in your browser, then return to choose"),
            ("q", "Stop here — completed changes are kept"),
        ]
        mapping = {option.key: option for option in options}
        while True:
            answer = select_option("What kind of video is this?", choices, "4")
            if answer == "o":
                if video.id.startswith("demo"):
                    console.print("Demo example: there is no real video to open.")
                elif not webbrowser.open(video.url):
                    console.print("The browser could not open. Copy the link shown above.")
                continue
            if answer in {"4", "q"}:
                return Decision("later" if answer == "4" else "quit")
            option = mapping[answer]
            if option.needs_episode_number:
                while True:
                    number = IntPrompt.ask("Main episode number", console=console)
                    if number > 0:
                        return replace(option.decision, episode_number=number)
                    console.print("The episode number must be positive.")
            return option.decision
    return choose


def show_report(console, profile: Profile, report: Report, dry_run=False):
    rows = report.planned if dry_run else [(video, target) for video, target, _ in report.added]
    if rows:
        table = Table(title="Planned additions" if dry_run else "Completed additions")
        table.add_column("Video")
        table.add_column("Playlist")
        for video, target in rows:
            table.add_row(Text(video.title), profile.labels[target])
        console.print(table)
    if report.errors:
        console.print(Panel(Text("\n".join(report.errors)), title="Incomplete update — retry required", border_style="red"))
    if dry_run:
        message = f"Simulation: {len(report.planned)} planned addition(s). No playlists or decisions were changed."
    elif report.errors:
        message = f"Incomplete update: {len(report.added)} confirmed addition(s). Resolve the error, then run again."
    elif report.added:
        label = "Update using your decisions" if any(row[2] for row in report.added) else "Automatic update"
        message = f"{label}: {len(report.added)} addition(s) completed in the playlists."
    elif report.pending:
        message = "No videos added. Some videos are waiting for your decision."
    elif report.descriptions:
        if report.updated_descriptions:
            message = "No videos added. Playlist description updated (Last updated on)."
        else:
            message = "No new videos to add. Verification date refreshed (Last checked on)."
    elif report.waiting:
        message = "No update performed. Upcoming videos or ongoing live streams will be checked again."
    elif report.excluded:
        message = "No new releases to add. Other uploads were excluded."
    else:
        message = "No new releases. No update performed."
    console.print(Panel(Text(message), title="Simulation summary" if dry_run else "Update summary", border_style="red" if report.errors else "green"))
    if report.pending:
        for video in report.pending:
            console.print(Panel(video_details(video), title="Video awaiting your decision", border_style="yellow"))
    if report.descriptions and (report.added or report.pending):
        console.print("Description tracking line refreshed.")
    if report.initialized:
        console.print(f"{'Simulated initialization' if dry_run else 'Initialization complete'}: the {report.preserved_count} videos already in your playlists were preserved.")
        if report.selection:
            cutoff = report.selection["cutoff"]
            boundary = "at or after" if report.selection["inclusive"] else "strictly after"
            console.print(Text(f"Start mode: {report.selection['mode']}. " + (f"Publication times {boundary} {cutoff}." if cutoff else "All accessible publications are eligible.")))
        if report.archived_count:
            console.print(f"{report.archived_count} older unselected uploads were left outside the playlists. They were not added retroactively.")
    if report.waiting:
        for deferred in report.waiting_details:
            console.print(Panel(video_details(deferred.video, deferred.reason), title="Video not ready to be added yet", border_style="yellow"))
        if not report.waiting_details:
            console.print(f"{report.waiting} video(s) not ready to be added: check again on the next run.")
    if report.removed:
        console.print(f"{report.removed} previously confirmed addition(s) are missing from their playlist; they were not reinserted.")
    if report.youtube_sort:
        console.print("YouTube controls positioning for automatically sorted playlists: keep Date published (oldest).")
    if report.stopped:
        console.print("Stopped. Saved decisions and completed additions will be used on the next run.")
