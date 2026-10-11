# YouTube playlist updater

A Python command-line tool that keeps your YouTube playlists up to date with uploads from a channel. Set duration thresholds in `config.toml` to exclude short uploads and optionally review borderline videos. The same rules work with any channel. Ambiguous videos can be reviewed with arrow-key menus; completed decisions are saved locally.

Requires **Python 3.11+ on macOS or Linux**. The execution lock uses Unix `fcntl`; Windows is not supported. You must own the destination playlists. This application adds videos and can optionally update descriptions; it does not delete playlist entries or videos.

## Install and configure

```sh
git clone https://github.com/CorbeusUltra/playlist-updater.git youtube-playlist-updater
cd youtube-playlist-updater
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp config.example.toml config.toml
```

Edit `config.toml`: replace the channel handle/ID and destination playlist ID. A channel is identified by `@handle` or `UC...`; a playlist ID is the `list=PL...` value in its YouTube URL. The example excludes uploads below one minute, asks about uploads lasting one to two minutes, and automatically selects longer finished videos. These thresholds are editable. Playlist descriptions are left unchanged.

Try the menus without Google credentials or network access:

```sh
./run.sh --profile example --demo
```

Use **↑/↓ to move, Enter to select, Ctrl+C to cancel**. Dates are text inputs. You can open an ambiguous video's link in your browser and return to make a decision. **Decide later** retains it for a subsequent run.

The installed `youtube-playlist-updater` command also works with an explicit configuration path, including when installed non-editably with `pip install .`:

```sh
.venv/bin/youtube-playlist-updater --config /absolute/path/to/config.toml --all --demo
```

Without `--config`, the installed command reads `./config.toml` in the current directory. `run.sh` first changes to the repository directory. Runtime directories are always located beside the configuration file, not inside the installed package.

## Connect your Google account

1. Create or select your own project in [Google Cloud Console](https://console.cloud.google.com/).
2. Enable **YouTube Data API v3**, configure the OAuth consent screen, and add your account as a test user if the application is in testing mode.
3. Create an OAuth client with application type **Desktop app** and download its JSON file.
4. Create `credentials/common/` beside your configuration file and place the download at `credentials/common/credentials.json`.
5. Run the access check and authorize in the browser using the Google account that owns your destination playlists:

```sh
./run.sh --all --check
```

See Google's [API setup guide](https://developers.google.com/youtube/v3/getting-started) and [desktop OAuth guide](https://developers.google.com/identity/protocols/oauth2/native-app). This is a local tool: each user supplies their own Google Cloud client, not a shared application credential.

The app retains the `youtube.force-ssl` OAuth scope used by the previous version. A free local callback port is selected when `oauth_port = 0`. Tokens are stored in `credentials/common/token.json` with private file permissions and refreshed when possible. Revoked or expired authorization can require another browser sign-in. `--non-interactive` never opens the authorization browser.

## Choose the initial selection

A profile without local state must explicitly choose how to start. In an interactive terminal, the first synchronization offers these modes:

| Mode | Which other videos become eligible? |
|---|---|
| `future` | Publications at or after the start of this first synchronization |
| `latest` | Publications strictly after the newest dated video from this source channel already selected in the destination playlists |
| `all` | All accessible uploads, including historical videos |
| `date` | Publications from the chosen calendar day, inclusive, beginning at 00:00 in the configured time zone |

Existing playlist entries are preserved in every mode, even if they would fail the current policy. Eligibility means the configured policy will assess a video; it does not override exclusions or human review.

Empty playlists work with `future`, `all` and `date`. `latest` requires a selected video from the source channel with a usable publication date; otherwise an interactive run asks for another mode. An automated run reports an error.

To initialize without an interactive terminal, set the mode in the profile:

```toml
[profiles.example]
# ...other profile fields...
initialization = "date"
start_date = "2026-06-01"
```

`start_date` is a quoted `YYYY-MM-DD` string and is used only with `date`. Set `[settings].timezone` to an IANA name such as `UTC` or `Europe/Zurich`; the public default is UTC.

The chosen mode and resolved time boundary are saved once. Editing these settings afterwards does not reset an existing state or change its selection boundary. This avoids accidentally revisiting a curated history. `--review-archives` explicitly revisits archived uploads; `--review-video VIDEO_ID --profile KEY` revisits one accessible video. Neither operation removes existing entries.

Preview before writing:

```sh
./run.sh --all --dry-run
./run.sh --all
```

An initial simulation asks for or uses the start mode but does not save it; the actual first run must choose again unless the mode is configured. `--dry-run` does not save decisions, add videos or change descriptions. Authentication may refresh a token, and a runtime lock is acquired. `--check` only verifies access and does not initialize the selection.

## Channels and duration rules

Profile keys are arbitrary names made from letters, digits, `_` and `-`; `all` and `quit` are reserved. Use `--profile KEY` to select one, `--all` for all, or the menu in an interactive terminal. Each profile has its own state; profiles with the same `credential_store` share one Google connection. Playlist IDs must be unique across the configuration.

Each profile uses duration rules and supports one or more named destination playlists. Every accepted video is added to all destinations configured in that profile. You do not need to write Python or choose a policy. Set these fields inside your profile in `config.toml`:

```toml
minimum_seconds = 60
review_max_seconds = 120
```

- Below `minimum_seconds`: exclude automatically.
- From `minimum_seconds` through `review_max_seconds`, inclusive: ask for a decision.
- Above the review range: add automatically.
- Set `review_max_seconds = 0` to disable duration-based review.

For example, `minimum_seconds = 60` and `review_max_seconds = 120` excludes videos below one minute and asks about videos lasting one to two minutes. These are configurable selection rules, **not an exact YouTube Shorts detector**: short regular videos may be excluded, and longer Shorts may pass your threshold. Set both values to zero to include every finished upload. Omitted thresholds also default to zero.

Two channel examples illustrate different duration settings:

| Channel | Duration selection | Configuration | Example playlist |
|---|---|---|---|
| Origami Beats | Exclude below 60 seconds; review 60–120 seconds inclusive; add longer videos | [Origami configuration](examples/config.origami.toml) | [All beats from Origamibeats](https://www.youtube.com/playlist?list=PL8YCuevUv1HuLkMFfpehRh_Uv7HQPBar0) |
| ego | Review videos up to 180 seconds inclusive; add longer videos | [ego configuration](examples/config.ego.toml) | [ego](https://www.youtube.com/playlist?list=PLN-9-hbH74LQ) |

These playlists illustrate personal selections, including initial history choices and individual review decisions. Your results depend on your own start mode, thresholds and choices. For a new setup, copy the chosen configuration to `config.toml` and replace the destination placeholder with a playlist you own. Both examples use the actual source channels, leave initialization interactive and disable description updates. The configurations contain no personal destination IDs, OAuth files or saved decisions.

## Start with a new empty playlist

1. Create an empty playlist in YouTube using your account. The tool fills an existing playlist; it does not create one.
2. Copy a configuration example, set the source channel and your destination playlist ID, and complete the Google setup above.
3. Choose `all` at the first-run menu to assess the complete accessible history, or configure `initialization = "all"` in the profile before previewing. Choose `future` or `date` if you only want a later period.
4. Run `./run.sh --profile KEY --dry-run`, inspect the proposed additions and pending reviews, then run `./run.sh --profile KEY` to synchronize. Accepted videos are added in publication order; ambiguous videos require a decision under the chosen policy.

Each new profile starts with its own empty decision record. No existing user's selection or migration files are needed.

## Ordering and optional descriptions

Playlists use publication ordering (`order = "published"`). Select **Date published (oldest)** in YouTube when using automatic date sorting. For manually sorted playlists, the engine calculates insertion positions from publication dates. It inserts new videos without reorganizing the entire existing playlist.

Description updates are disabled by default. Enable `update_description = true` to refresh tracking after additions; also set `description_every_scan = true` to refresh after each successful scan. An optional `description` field supplies a managed body; omitting it preserves the existing body.

Tracking replaces legacy markers with one final line: **Last updated on:** after additions or a body change, otherwise **Last checked on:**. A subsequent unchanged scan uses **checked** again. English month names and the configured time zone are used. Titles, tags, language and privacy are preserved. Checks and simulations never write descriptions.

## What is fetched and stored?

Every synchronization reads **all pages of the accessible channel uploads and destination playlists**. It then fetches video metadata in batches of up to 50, with a cache shared within that run. It does not use a publication-date watermark to stop reading. This makes deferred videos, partial failures and remote playlist membership visible again, at the cost of reads proportional to the accessible catalogue. It uses the channel's uploads playlist rather than `search`. Each page and each insertion/update consumes API quota; see Google's [quota table](https://developers.google.com/youtube/v3/determine_quota_cost).

```text
config.toml                         Your profiles and rules (not versioned)
credentials/<store>/credentials.json Your Google OAuth client (not versioned)
credentials/<store>/token.json       Your authorization token (not versioned)
data/<profile>.json                 Persistent selection decisions (not versioned)
data/<profile>.previous.json        Previous saved state (not versioned)
data/sync.lock                      Shared execution lock (not versioned)
```

No video or audio files are downloaded. State version 2 stores channel/destination bindings, the initial boundary, decisions (`add`, `ignore`, `review`, `archive`), relevant video metadata, fingerprints, human-choice flags, requested destinations and completed additions. It also records scan/modification timestamps and descriptions awaiting retry. An archive is an upload outside the initial selection, not a downloaded file.

`archive` means **outside the chosen period**, without applying the selection rules to that upload. For example, a long video before a configured start date is archived. `ignore` means **excluded by a rule or by your explicit decision**: for example, a recent video below the configured minimum duration. Both remain outside the playlist during an ordinary run, for different reasons. `--review-archives` applies the policy to archived uploads; it does not cancel explicit exclusions. Use `--review-video` to revisit an individual exclusion.

The same decision system is used for every channel, with a separate `data/<profile>.json` for each profile. It is not specific to Origami or legacy imports; the same distinction applies to a new playlist initialized with a date or future-publications limit.

Existing selections are imported without retroactive filtering. Human choices remain valid if titles change. Automatic exclusions are reconsidered when the recorded metadata changes; changing thresholds alone does not reset old decisions. Upcoming premieres, live streams and videos with missing date/duration wait for usable metadata. Already processed videos do not become new pending releases.

An addition that succeeds in one destination resumes only in the missing destinations. The API's insertion receipt confirms a successful write even if subsequent list responses have not yet caught up. Confirmed entries are retained in the current scan's working playlist snapshot to calculate subsequent insertion positions.

Before each addition, a `pending_writes` checkpoint is saved in the decision. If the response is lost or unusable, the app performs up to four read-only confirmation attempts with short pauses. An unresolved attempt remains pending across runs: running again checks its visibility without sending another insertion. Once the entry is visible, it is confirmed and the checkpoint is cleared. A definitive API rejection clears the checkpoint so the operation can be retried after its cause is resolved. Existing version 2 states without this optional field remain compatible.

If an uncertain attempt never appears, check the playlist yourself before using `--review-video VIDEO_ID --profile KEY`. Choosing inclusion explicitly permits another attempt; deferring preserves the pending checkpoint. A confirmed video subsequently removed manually is not reinserted. Corrupt state or mismatched channel/destination bindings stop the profile. State writes are atomic with a rolling previous-state backup; a shared lock prevents concurrent runs within the same configuration directory.

## Upgrade from the previous version

Version 0.2.0 replaces `.env` configuration and the `script/run.py` entry point. Python 3.10 is no longer supported.

1. Create the new TOML configuration using your previous `CHANNEL_ID` and `PLAYLIST_ID`, the duration thresholds you want. Convert the old duration threshold to `minimum_seconds`; use `review_max_seconds = 0` to retain a simple exclusion threshold. The old `DRY_RUN` setting becomes the `--dry-run` flag.
2. Copy your existing OAuth client and token from `credentials/` into `credentials/common/`, keeping the originals until verification.
3. If no new state exists for that profile, import the previous `data/playlist_data.json`:

```sh
./run.sh --profile example --import-state /absolute/path/to/playlist_data.json
./run.sh --profile example --dry-run
```

Import is separate from synchronization: it resolves the channel and checks ownership, but does not add videos or update descriptions. The source file is preserved, and an existing destination state is never overwritten. Legacy mono-playlist imports require one matching destination and a usable historical date. Matching version 2 states are also supported. Historical decisions and recorded archives are preserved.

A persistent publication boundary is enforced when the state contains `selection`, as in a newly initialized profile. Older states without `selection` use their `baseline` during initial reconciliation, but do not impose a permanent cutoff on uploads discovered in later scans. Importing or loading an older state does not automatically add `selection`. Editing initialization settings does not migrate an existing state.

Existing duration-based version 2 states remain usable without import or reinitialization. Keep their profile keys, channel/destination bindings and explicit duration thresholds. The previous `review_min_seconds` spelling remains accepted, but new configurations should use `minimum_seconds`.

## Development

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
```

Tests use fake services, not your Google account. CI tests Python 3.11–3.14 and checks both editable and wheel installations with an external configuration and a demo requiring no Google access.

Local configuration, credentials, state, private notes and build artifacts are excluded from Git. Public examples contain placeholders. The optional `launch.command` is a macOS/iTerm convenience; the CLI does not require iTerm or a Desktop shortcut.

MIT — see [LICENSE](LICENSE).
