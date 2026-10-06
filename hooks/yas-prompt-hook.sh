#!/bin/sh
# Runs yas-prompt-hook.py on the private CPython that ops/install.sh provisions
# under the plugin root (the statusline's own interpreter), so the hook does not
# depend on a bare `python3` on PATH -- on Windows that is often the Microsoft
# Store stub. Falls back to python3 before /yas:init has provisioned one.
root=$(cd "$(dirname "$0")/.." && pwd)
hook="$root/hooks/yas-prompt-hook.py"
for py in "$root"/.python/cpython-*/bin/python3 "$root"/.python/cpython-*/python.exe; do
    [ -x "$py" ] && exec "$py" "$hook"
done
exec python3 "$hook"
