import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .auth import connect
from .config import load_config
from .engine import synchronize
from .migration import convert_state
from .storage import load, locked, save
from .ui import chooser, initialization_chooser, select_profiles, show_report
from .youtube import error_reason


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Synchronize YouTube playlists using configurable selection policies.")
    parser.add_argument("--config", type=Path, default=None, help="Configuration file (default: ./config.toml)")
    parser.add_argument("--profile", metavar="KEY", help="Select a configured profile")
    parser.add_argument("--all", action="store_true", help="Select all configured profiles")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="Preview without changing playlists or saved decisions")
    modes.add_argument("--check", action="store_true", help="Verify authentication and playlist access without modifying playlists")
    modes.add_argument("--demo", action="store_true", help="Try the menus without YouTube access or saving decisions")
    modes.add_argument("--import-state", type=Path, metavar="PATH", help="Import legacy or version 2 state without synchronizing")
    parser.add_argument("--non-interactive", action="store_true", help="Defer ambiguous videos and do not launch browser authentication")
    parser.add_argument("--review-archives", action="store_true", help="Explicitly revisit uploads outside the initial selection")
    parser.add_argument("--review-video", metavar="VIDEO_ID", help="Review a specific video decision in --profile")
    args = parser.parse_args(argv)
    if args.all and args.profile:
        parser.error("Choose either --all or --profile.")
    if (args.review_video or args.import_state) and not args.profile:
        parser.error("--review-video and --import-state require --profile.")
    if args.import_state and (args.review_video or args.review_archives):
        parser.error("State import is separate from video review.")
    console = Console()
    interactive = sys.stdin.isatty() and not args.non_interactive
    console.print(Panel("[bold]YouTube — playlist updater[/bold]", border_style="cyan"))
    try:
        config_path = (args.config or Path.cwd() / "config.toml").expanduser().resolve()
        root = config_path.parent
        profiles, auth = load_config(config_path)
        if args.profile:
            if args.profile not in profiles:
                raise ValueError(f"Unknown profile {args.profile!r}. Configured profiles: {', '.join(profiles)}.")
            selected = [profiles[args.profile]]
        elif args.all:
            selected = list(profiles.values())
        elif interactive:
            selected = select_profiles(console, profiles)
        else:
            raise RuntimeError("Specify --profile KEY or --all without an interactive terminal.")
        if not selected:
            console.print("No update requested.")
            return 0
        if args.demo:
            console.print("[yellow]DEMO — no YouTube access, no decisions saved.[/yellow]")
            for profile in selected:
                console.rule(Text(profile.label))
                video = profile.policy.demo_video()
                decision = chooser(console, profile, interactive)(video, profile.policy.classify(video))
                console.print(Text(f"Demo decision: {decision.nature or decision.action}. No changes made."))
                if decision.action == "quit":
                    break
            return 0
        failures = False
        # Reject an unspecified automated first run before creating a lock or touching OAuth.
        if not interactive and not (args.check or args.import_state):
            ready = []
            for profile in selected:
                if profile.initialization is None and not (root / "data" / f"{profile.key}.json").exists():
                    console.print(Text(f"{profile.label}: choose initialization = 'future', 'latest', 'all' or 'date' in the configuration before the first non-interactive run.", style="red"))
                    failures = True
                else:
                    ready.append(profile)
            selected = ready
        if not selected:
            return 1
        if args.import_state and (root / "data" / f"{selected[0].key}.json").exists():
            raise RuntimeError("An active state already exists. Import refuses to overwrite it.")
        services, unavailable_stores = {}, set()
        with locked(root / "data" / "sync.lock"):
            for profile in selected:
                console.rule(Text(profile.label))
                try:
                    store = profile.credential_store
                    if store not in services:
                        if store in unavailable_stores:
                            raise RuntimeError("Shared Google authentication failed. Resolve the issue and run again.")
                        try:
                            services[store] = connect(root / "credentials" / store, auth.get("oauth_port", 0), interactive, lambda message: console.print(Text(message, style="yellow")))
                        except Exception:
                            unavailable_stores.add(store)
                            raise
                    service = services[store]
                    state_path = root / "data" / f"{profile.key}.json"
                    if args.import_state:
                        if state_path.exists():
                            raise RuntimeError("An active state already exists. Import refuses to overwrite it.")
                        source = args.import_state.expanduser().resolve()
                        data = json.loads(source.read_text(encoding="utf-8"))
                        channel_id, _ = service.channel(profile.channel)
                        service.validate_targets(profile.playlist_ids)
                        state = convert_state(data, profile, channel_id)
                        save(state_path, state)
                        console.print(Text(f"Imported {len(state['decisions'])} decisions into {state_path}. Source preserved. No playlists changed."))
                        continue
                    if args.check:
                        with console.status("Verifying authentication and playlist access…"):
                            channel_id, _ = service.channel(profile.channel)
                            titles = service.validate_targets(profile.playlist_ids)
                            counts = {key: len(service.items(pid)) for key, pid in profile.playlist_ids.items()}
                        console.print(Text(f"Channel: {profile.channel} ({channel_id})"))
                        for key, pid in profile.playlist_ids.items():
                            console.print(Text(f"{titles[key]} — {counts[key]} video(s)\nhttps://www.youtube.com/playlist?list={pid}"))
                        console.print("[green]Access verified. No playlists changed.[/green]")
                        continue
                    state = load(state_path)
                    spinner = console.status("Reading channel uploads and playlists…")
                    spinner.start()
                    def reading(message):
                        if message is None:
                            spinner.stop()
                        else:
                            spinner.update(message)
                    def added(video, target, human):
                        console.print(Text(f"✓ {'Approved decision' if human else 'Automatic addition'} · {profile.labels[target]} · {video.title}", style="green"))
                    try:
                        report = synchronize(service, profile, state, state_path, chooser(console, profile, interactive), dry_run=args.dry_run, review_archives=args.review_archives, review_video=args.review_video, on_added=added, on_read=reading, choose_initialization=initialization_chooser(console, profile) if interactive else None)
                    finally:
                        spinner.stop()
                    show_report(console, profile, report, args.dry_run)
                    failures |= bool(report.errors)
                    if report.stopped:
                        break
                except (KeyboardInterrupt, EOFError):
                    raise
                except Exception as exc:
                    failures = True
                    console.print(Panel(Text(error_reason(exc)), title="Update interrupted", border_style="red"))
        return 1 if failures else 0
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Stopped. Saved decisions and completed additions are kept.[/yellow]")
        return 130
    except Exception as exc:
        console.print(Panel(Text(error_reason(exc)), title="The update could not finish", border_style="red"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
