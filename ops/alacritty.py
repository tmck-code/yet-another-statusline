#!/usr/bin/env python3

# run alacritty -v, watch output for resize logs, and print them in a more human readable format

import os, signal
import sys
import subprocess

terminal_pixel_width, cell_pixel_width, columns = 0, 0, 0

for line in map(str.strip, sys.stdin):
    if 'Width: ' in line:
        terminal_pixel_width = int(line.split('Width: ')[1].split(',')[0])
        print('woohoo! found terminal pixel width:', terminal_pixel_width, file=sys.stderr)
    elif 'Cell size: ' in line:
        cell_pixel_width = int(line.split('Cell size: ')[1].split(' x ')[0])
        print('woohoo! found cell pixel width:', cell_pixel_width, file=sys.stderr)
    # else:
    #     print('not a match:', line.strip(), file=sys.stderr)

    if terminal_pixel_width and cell_pixel_width:
        new_columns = terminal_pixel_width // cell_pixel_width
        if new_columns != columns:
            print('terminal width changed! new columns:', new_columns, file=sys.stderr)
            columns = new_columns
            with open(f'{os.environ["HOME"]}/.claude/terminal-width', 'w') as f:
                f.write(str(columns))
            try:
                r = subprocess.run(['pgrep', '-f', 'claude'], capture_output=True, text=True)
                print('killing claude processes:', r.stdout.strip(), file=sys.stderr)
                for pid in r.stdout.split():
                    print('sending SIGWINCH to pid:', pid, file=sys.stderr)
                    os.kill(int(pid), signal.SIGWINCH)
            except Exception as e:
                print('error sending SIGWINCH to claude processes:', e, file=sys.stderr)
                pass

        else:
            print('terminal width unchanged:', columns, file=sys.stderr)

