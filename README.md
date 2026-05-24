# YAS! (Yet Another Statusline)

<img width="1211" height="237" alt="image" src="https://github.com/user-attachments/assets/8e23b3ca-8d8f-4401-b564-e1b065521fd4" />

_Most common form is displaying these stats, which include the loaded plugins & skills. Extra sections appear as needed_

To install (note: currently requires the Iosevka ["Nerd font"](https://www.nerdfonts.com/font-downloads) for the icons):

```bash
make install
```

This symlinks the files into your `~/.claude/` user dir, allowing you to easily update them via a `git pull`

## Demo

A dummy session to demonstrate the layout:

<img width="1264" height="552" alt="statusline-demo" src="https://github.com/user-attachments/assets/64e941b8-90a4-4ec8-98e0-973a57c04212" />

## Layout Reference

<img width="1723" height="688" alt="image" src="https://github.com/user-attachments/assets/03c65cb2-f533-4194-94df-416d9b7e820e" />

## Widths

The statusline also renders differently according to available width

| mode | width | screenshot |
|------|-------|------------|
| "medium" | <=80 pixels | <img width="839" height="122" alt="image" src="https://github.com/user-attachments/assets/56519acc-a65c-446a-a938-5a14f093c817" /> |
| "narrow" | <=55 pixels | <img width="537" height="120" alt="image" src="https://github.com/user-attachments/assets/7254cbb7-ea37-4f41-8adc-506cf6b48033" /> |

---

## Commands

To demo/test:

```bash
make demo
```
