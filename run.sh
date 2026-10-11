#!/bin/bash
set -eu
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
if [ ! -x .venv/bin/python ]; then
    printf 'Python environment missing. See the README for installation instructions.\n' >&2
    exit 1
fi
exec .venv/bin/python -m youtube_playlist_updater.cli "$@"
