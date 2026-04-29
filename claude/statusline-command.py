#!/usr/bin/env python3
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import NamedTuple


class C:
    R = "\033[0m"
    PWD = "\033[38;5;75m"
    BRANCH = "\033[38;5;114m"
    COMMIT = "\033[38;5;244m"
    DIRTY = "\033[38;5;214m"
    SESSION = "\033[38;5;244m"
    MODEL = "\033[38;5;183m"
    SKILLS = "\033[38;5;222m"
    TIME = "\033[38;5;244m"
    TOK = "\033[38;5;116m"
    COST = "\033[38;5;210m"
    BAR_FILL = "\033[38;5;114m"
    BAR_EMPTY = "\033[38;5;238m"
    LABEL = "\033[38;5;244m"
    CTX = "\033[38;5;216m"


HOME = Path.home()
# TOKEN_LOG = HOME / ".claude" / "statusline-tokens.log"
# INPUT_DUMP_DIR = HOME / ".claude" / "statusline-output"
# USER_SETTINGS = HOME / ".claude" / "settings.json"
# SKILLS_DIR = HOME / ".claude" / "skills"
TOKEN_LOG = Path(__file__).parent / "statusline-tokens.log"
INPUT_DUMP_DIR = Path(__file__).parent / "statusline-input-dumps"
USER_SETTINGS = Path(__file__).parent / "settings.json"
SKILLS_DIR = Path(__file__).parent / "skills"


class Model(NamedTuple):
    display_name: str | None = None
    id: str | None = None

    @property
    def name(self) -> str:
        return self.display_name or self.id or "unknown"

    @property
    def context_limit(self) -> int:
        return 200_000

    @property
    def cost_rates(self) -> tuple[float, float]:
        n = self.name.lower()
        if "opus" in n:
            return 15.00, 75.00
        if "haiku" in n:
            return 0.80, 4.00
        return 3.00, 15.00


class ContextWindow(NamedTuple):
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    used_percentage: float | None = None


class Workspace(NamedTuple):
    project_dir: str | None = None


class GitInfo(NamedTuple):
    branch: str
    commit: str


class OpenSpecChange(NamedTuple):
    name: str
    done: int
    total: int


@dataclass
class Info:
    cwd: str
    model: Model
    session_id: str
    transcript_path: str
    context_window: ContextWindow
    workspace: Workspace

    @classmethod
    def from_json(cls, d: dict) -> "Info":
        m = d.get("model") or {}
        cw = d.get("context_window") or {}
        ws = d.get("workspace") or {}
        return cls(
            cwd=d.get("cwd") or "",
            model=Model(
                display_name=m.get("display_name"),
                id=m.get("id"),
            ),
            session_id=d.get("session_id") or "",
            transcript_path=d.get("transcript_path") or "",
            context_window=ContextWindow(
                total_input_tokens=int(cw.get("total_input_tokens") or 0),
                total_output_tokens=int(cw.get("total_output_tokens") or 0),
                used_percentage=cw.get("used_percentage"),
            ),
            workspace=Workspace(project_dir=ws.get("project_dir")),
        )

    @cached_property
    def short_pwd(self) -> str:
        path = self.cwd
        try:
            home = str(HOME)
            if path == home or path.startswith(home + "/"):
                path = "~" + path[len(home):]
        except Exception:
            pass
        return re.sub(r"([^/])[^/]*/", r"\1/", path)

    @cached_property
    def elapsed(self) -> str:
        if not self.transcript_path:
            return ""
        p = Path(self.transcript_path)
        try:
            start = p.stat().st_mtime
        except OSError:
            return ""
        secs = int(time.time() - start)
        if secs < 0:
            return ""
        h, rem = divmod(secs, 3600)
        m = rem // 60
        return f"{h}h{m}m" if h > 0 else f"{m}m"

    @cached_property
    def skills(self) -> list[str]:
        if not SKILLS_DIR.is_dir():
            return []
        names: set[str] = set()
        for child in SKILLS_DIR.iterdir():
            if child.is_dir() and (child / "SKILL.md").is_file():
                names.add(child.name)
        for f in SKILLS_DIR.glob("*.md"):
            if f.name != "SKILL.md":
                names.add(f.stem)
        return sorted(names)

    @cached_property
    def skills_display(self) -> str:
        if not self.skills:
            return ""
        if len(self.skills) == 1:
            return self.skills[0]
        return f"skills({len(self.skills)})"

    @cached_property
    def plugins(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        candidates = [USER_SETTINGS]
        if self.workspace.project_dir:
            candidates.append(Path(self.workspace.project_dir) / ".claude" / "settings.json")
        for path in candidates:
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            enabled = data.get("enabledPlugins") or {}
            if not isinstance(enabled, dict):
                continue
            for key, value in enabled.items():
                if value is not True or key in seen:
                    continue
                seen.add(key)
                out.append(key.split("@", 1)[0])
        return out

    @cached_property
    def git(self) -> GitInfo | None:
        curr = Path(self.cwd) if self.cwd else None
        repo: Path | None = None
        while curr is not None:
            if (curr / ".git").exists():
                repo = curr
                break
            if curr.parent == curr:
                break
            curr = curr.parent
        if repo is None:
            return None
        gitdir = repo / ".git"
        head_path = gitdir / "HEAD"
        if not head_path.is_file():
            return None
        head = head_path.read_text().strip()
        if head.startswith("ref:"):
            branch = head.split("/")[-1]
        elif head:
            return GitInfo(branch=f"d:{head[:7]}", commit=head[:9])
        else:
            return None
        commit = ""
        ref_path = gitdir / "refs" / "heads" / branch
        if ref_path.is_file():
            commit = ref_path.read_text().strip()[:9]
        elif (gitdir / "ORIG_HEAD").is_file():
            commit = (gitdir / "ORIG_HEAD").read_text().strip()[:9]
        return GitInfo(branch=branch, commit=commit)

    @cached_property
    def openspec(self) -> list[OpenSpecChange]:
        curr = Path(self.cwd) if self.cwd else None
        root: Path | None = None
        while curr is not None:
            candidate = curr / "openspec"
            if candidate.is_dir():
                root = candidate
                break
            if curr.parent == curr:
                break
            curr = curr.parent
        if root is None:
            return []
        out: list[OpenSpecChange] = []
        for tasks_md in sorted(root.rglob("tasks.md")):
            if "archive" in tasks_md.parts:
                continue
            try:
                text = tasks_md.read_text()
            except OSError:
                continue
            done = 0
            todo = 0
            for line in text.splitlines():
                stripped = line.lstrip()
                if stripped.startswith("- [ ]"):
                    todo += 1
                elif stripped.startswith("- [x]") or stripped.startswith("- [X]"):
                    done += 1
            total = done + todo
            if total == 0:
                continue
            out.append(OpenSpecChange(name=tasks_md.parent.name, done=done, total=total))
        return out

    @cached_property
    def day_tokens(self) -> tuple[int, int]:
        if not TOKEN_LOG.is_file():
            return 0, 0
        today = time.strftime("%Y-%m-%d")
        in_total = 0
        out_total = 0
        try:
            for line in TOKEN_LOG.read_text().splitlines():
                parts = line.split()
                if len(parts) != 4 or parts[0] != today:
                    continue
                try:
                    in_total += int(parts[2])
                    out_total += int(parts[3])
                except ValueError:
                    continue
        except OSError:
            return 0, 0
        return in_total, out_total

    @cached_property
    def session_cost(self) -> float:
        ri, ro = self.model.cost_rates
        ti = self.context_window.total_input_tokens
        to = self.context_window.total_output_tokens
        return (ti * ri + to * ro) / 1_000_000

    @cached_property
    def day_cost(self) -> float:
        ri, ro = self.model.cost_rates
        di, do = self.day_tokens
        return (di * ri + do * ro) / 1_000_000

    def persist_input(self, raw: str) -> None:
        try:
            INPUT_DUMP_DIR.mkdir(parents=True, exist_ok=True)
            stamp = int(time.time())
            (INPUT_DUMP_DIR / f"statusline.{stamp}.json").write_text(raw)
        except OSError:
            pass

    def update_token_log(self) -> None:
        sid = self.session_id
        ti = self.context_window.total_input_tokens
        to = self.context_window.total_output_tokens
        if not sid or (ti == 0 and to == 0):
            return
        today = time.strftime("%Y-%m-%d")
        kept: list[str] = []
        if TOKEN_LOG.is_file():
            try:
                for line in TOKEN_LOG.read_text().splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] == sid:
                        continue
                    if line:
                        kept.append(line)
            except OSError:
                kept = []
        kept.append(f"{today} {sid} {ti} {to}")
        try:
            TOKEN_LOG.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_LOG.write_text("\n".join(kept) + "\n")
        except OSError:
            pass

    def _fmt_tok(self, n: int) -> str:
        if n >= 1000:
            return f"{n / 1000:.1f}K"
        return str(n)

    def _line1(self) -> str:
        out = f"{C.PWD}{self.short_pwd}{C.R}"
        g = self.git
        if g is not None and g.branch:
            out += (
                f" {C.LABEL}∈{C.R}"
                f" {C.BRANCH}{g.branch}{C.R}"
                f"{C.LABEL}/{C.R}"
                f"{C.COMMIT}{g.commit}{C.R}"
                f" {C.SESSION}[{self.session_id}]{C.R}"
            )
        return out

    def _line2(self) -> str:
        out = f"{C.MODEL}💻 {self.model.name}{C.R}"
        if self.skills:
            out += f" {C.LABEL}|{C.R} [{C.SKILLS}{self.skills_display}{C.R}]"
        pct = self.context_window.used_percentage
        if pct is not None:
            p = float(pct)
            pi = int(round(p))
            used_tok = self.context_window.total_input_tokens + self.context_window.total_output_tokens
            limit = self.model.context_limit
            used_s = self._fmt_tok(used_tok)
            limit_s = self._fmt_tok(limit)
            bar_w = 15
            filled = int(p * bar_w / 100)
            if p >= 80:
                fill_color = "\033[38;5;196m"
            elif p >= 60:
                fill_color = "\033[38;5;214m"
            else:
                fill_color = C.BAR_FILL
            bar = f"{fill_color}{'█' * filled}{C.R}{C.BAR_EMPTY}{'░' * (bar_w - filled)}{C.R}"
            out += f"{C.LABEL}|{C.R} \033[38;5;15;1m✪ {bar} {C.CTX}{used_s}/{limit_s}{C.R} {C.CTX}{pi}%{C.R}"
        if self.plugins:
            joined = ",".join(self.plugins)
            out += f" {C.LABEL}|{C.R} {C.SKILLS}{joined}{C.R}"
        return out

    def _line3(self) -> str:
        ti = self.context_window.total_input_tokens
        to = self.context_window.total_output_tokens
        di, do = self.day_tokens
        ti_s = self._fmt_tok(ti)
        to_s = self._fmt_tok(to)
        di_s = self._fmt_tok(di)
        do_s = self._fmt_tok(do)
        # time_str = time.strftime("%H:%M:%S")
        # out = f"{C.TIME}{time_str}{C.R}"
        # if self.elapsed:
        #     out += f"{C.LABEL}(+{self.elapsed}){C.R}"
        out = f"⬙ {C.LABEL}↓ {C.R}{C.TOK}{ti_s}{C.R}"
        out += f"{C.LABEL}↑ {C.R}{C.TOK}{to_s}{C.R}"
        if di_s != ti_s or do_s != to_s:
            out += f" / {C.LABEL}↓ {C.R}{C.TOK}{di_s}{C.R}"
            out += f"{C.LABEL}↑ {C.R}{C.TOK}{do_s}{C.R}"
        sc = f"{self.session_cost:.4f}"
        dc = f"{self.day_cost:.4f}"
        out += f" 💰 {C.COST}${sc}{C.R}"
        if dc != sc:
            out += f"{C.LABEL}/{C.R}{C.COST}${dc}{C.R}"
        return out

    def _openspec_lines(self) -> list[str]:
        lines: list[str] = []
        bar_width = 30
        for change in self.openspec:
            filled = change.done * bar_width // change.total
            bar_filled = "█" * filled
            bar_empty = "░" * (bar_width - filled)
            pct = change.done * 100 // change.total
            ratio = f"{change.done}/{change.total}"
            line = (
                f"{C.BAR_FILL}{bar_filled}{C.R}{C.BAR_EMPTY}{bar_empty}{C.R}"
                f" {C.LABEL}{ratio}{C.R} \033[1m{pct:>3}%{C.R}"
                f" {C.LABEL}\033[3m{change.name}{C.R}"
            )
            lines.append(line)
        return lines

    def render(self) -> str:
        parts = [self._line1(), self._line2(), self._line3()]
        parts.extend(self._openspec_lines())
        return "\n".join(parts)


def main() -> None:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}
    info = Info.from_json(data)
    info.persist_input(raw)
    info.update_token_log()
    sys.stdout.write(info.render())


if __name__ == "__main__":
    main()
