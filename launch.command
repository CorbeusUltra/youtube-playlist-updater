#!/bin/zsh
PROJECT="${0:A:h}"

if [[ "${TERM_PROGRAM:-}" != 'iTerm.app' ]]; then
    /usr/bin/osascript - "$0" "$@" <<'APPLESCRIPT'
on run argv
    set launcher to quoted form of (item 1 of argv)
    if (count of argv) > 1 then
        repeat with arg in items 2 thru -1 of argv
            set launcher to launcher & " " & quoted form of arg
        end repeat
    end if
    tell application "iTerm"
        activate
        if (count of windows) is 0 then
            set taskWindow to (create window with default profile)
            set taskSession to current session of taskWindow
        else
            tell current window
                set taskTab to (create tab with default profile)
                set taskSession to current session of taskTab
            end tell
        end if
        tell taskSession to write text launcher
    end tell
end run
APPLESCRIPT
    exit $?
fi

(( $+functions[maximize_window] )) && maximize_window
if (( $+functions[notify] )); then
    notify --title 'YouTube — playlists' "$PROJECT/run.sh" "$@"
else
    "$PROJECT/run.sh" "$@"
fi
launch_status=$?
print
read -r '?Press Enter to close this tab… '
exit "$launch_status"
