#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tmux_csv_command_scheduler_fastfill_enterfix.py

Read simulation commands from one or more CSV files and greedily dispatch them,
in the order given on the command line and then in CSV row order, to idle panes
inside one tmux session. This fast-fill variant is meant to keep eligible panes
occupied whenever pending jobs exist.

Fast-fill behavior in this version:
  - The scheduler refuses to use a whole session unless --panes is explicitly
    provided, or unless the operator deliberately passes --allow-all-panes.
  - When run inside tmux, the pane running the scheduler is excluded unless
    --include-current-pane is explicitly provided.
  - A pane that is BUSY at scheduler startup is protected: no key is sent to it
    while a foreground command is running. The default is now
    --initial-busy-policy wait, so it becomes eligible as soon as it naturally
    returns to an interactive shell.
  - The exact target pane IDs are frozen at startup, so later tmux layout/index
    changes do not accidentally add new panes.
  - Immediately before dispatching a job, the scheduler refreshes that pane's
    status and sends the command only if it is still idle. The default check is
    intentionally faster than the conservative version to reduce idle gaps.
  - Before sending the job command, the scheduler can clear only the current
    shell input line with non-interruptive editing keys. It does not send
    Ctrl-C, does not kill processes, does not clear the pane screen, and does
    not rename or close tmux windows/panes.
  - This enter-fix variant does not use paste-buffer followed by a separate
    tmux send-keys Enter operation. It sends the generated command and Enter
    through one tmux send-keys call, reducing cases where the command appears
    in the pane but does not start until a manual Enter is pressed.

The default CSV command column is "command". When multiple CSV files are
provided, their command rows are concatenated in the exact order given on the
command line. Each dispatched job is wrapped so that stdout/stderr are written
both to the tmux pane and to a per-job log file.
The scheduler prints real-time progress to its own terminal.

Linux/tmux assumptions:
  - Linux /proc is available.
  - tmux is installed.
  - Target panes are interactive shells such as bash/zsh/sh.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional, Sequence, Set, Tuple


DEFAULT_SHELLS = {
    "bash", "zsh", "sh", "dash", "fish", "tcsh", "csh", "ksh", "mksh", "xonsh"
}

# Runtime-configured by --idle-detection.
# relaxed: shell name plus /proc must not clearly contradict idleness.
# strict: previous safest /proc foreground-process-group check.
# shell-only: shell name only; fastest but less safe.
IDLE_DETECTION_MODE = "relaxed"

PANE_FORMAT = "\t".join([
    "#{pane_id}",
    "#{session_name}",
    "#{window_index}",
    "#{pane_index}",
    "#{window_name}",
    "#{pane_tty}",
    "#{pane_pid}",
    "#{pane_current_command}",
    "#{pane_dead}",
])


@dataclass
class CommandItem:
    """One runnable CSV row from one source CSV file."""
    index: int          # 1-based global job id after merging all CSV files
    csv_file: str       # resolved source CSV path
    csv_name: str       # source CSV basename
    csv_order: int      # 1-based order of the source CSV on the command line
    local_index: int    # 1-based runnable command index within that CSV
    csv_row: int        # 1-based physical CSV row number, including header
    command: str
    metadata: Dict[str, str]


@dataclass
class Pane:
    pane_id: str
    session: str
    window_index: str
    pane_index: str
    window_name: str
    tty: str
    pane_pid: int
    current_command: str
    dead: bool

    @property
    def target_short(self) -> str:
        return f"{self.window_index}.{self.pane_index}"

    @property
    def target_full(self) -> str:
        return f"{self.session}:{self.window_index}.{self.pane_index}"


@dataclass
class RunningJob:
    command_item: CommandItem
    pane_id: str
    target_full: str
    log_file: Path
    done_file: Path
    script_file: Path
    start_time: str
    start_epoch: float
    recovered: bool = False


class SchedulerLogger:
    """Print progress to stdout and mirror it to scheduler_progress.log."""

    def __init__(self, log_file: Path) -> None:
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.log_file.open("a", encoding="utf-8")

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass

    def log(self, message: str = "") -> None:
        line = message
        print(line, flush=True)
        self._fh.write(line + "\n")
        self._fh.flush()


def now_str() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def timestamp_for_path() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def seconds_to_hms(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fail(msg: str, code: int = 1) -> None:
    raise SystemExit(f"[ERROR] {msg}")


def run_tmux(args: Sequence[str], *, check: bool = True, capture: bool = True) -> str:
    cmd = ["tmux", *args]
    try:
        p = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError:
        fail("tmux not found. Please install tmux or load it into PATH.")
    if check and p.returncode != 0:
        stderr = (p.stderr or "").strip()
        fail(f"tmux command failed: {' '.join(shlex.quote(x) for x in cmd)}\n{stderr}")
    return (p.stdout or "").rstrip("\n")


def list_sessions() -> List[str]:
    out = run_tmux(["list-sessions", "-F", "#{session_name}"], check=False)
    return [x.strip() for x in out.splitlines() if x.strip()]


def current_tmux_session() -> Optional[str]:
    if "TMUX" not in os.environ:
        return None
    out = run_tmux(["display-message", "-p", "#{session_name}"], check=False)
    return out.strip() or None


def resolve_session(session: Optional[str]) -> str:
    sessions = list_sessions()
    if session:
        if session not in sessions:
            fail(f"tmux session {session!r} not found. Existing sessions: {sessions}")
        return session

    cur = current_tmux_session()
    if cur:
        return cur

    if len(sessions) == 1:
        return sessions[0]
    if not sessions:
        fail("no tmux session found. Start tmux first, or pass --session.")
    fail(f"multiple tmux sessions found: {sessions}. Please pass --session.")


def parse_csv_commands(
    csv_path: Path,
    cmd_col: str = "command",
    *,
    start_index: int = 1,
    csv_order: int = 1,
    limit: Optional[int] = None,
) -> List[CommandItem]:
    """Parse one CSV file and return runnable command rows.

    The returned CommandItem.index values are global indexes starting at
    start_index. local_index is the per-file runnable command index.
    """
    if not csv_path.exists():
        fail(f"CSV file not found: {csv_path}")
    if not csv_path.is_file():
        fail(f"CSV path is not a regular file: {csv_path}")

    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        # These run-table CSV files are comma-separated and contain shell commands
        # with many spaces. csv.Sniffer can mis-detect whitespace as the delimiter,
        # so use the standard comma-separated dialect explicitly.
        reader = csv.DictReader(f, dialect=csv.excel)
        if reader.fieldnames is None:
            fail(f"CSV header not found in {csv_path}. This scheduler expects a header row and a command column.")

        fieldnames = [x.strip() if x is not None else "" for x in reader.fieldnames]
        fieldname_map = {name.lower(): name for name in fieldnames}

        requested = cmd_col.strip()
        if requested in fieldnames:
            actual_cmd_col = requested
        elif requested.lower() in fieldname_map:
            actual_cmd_col = fieldname_map[requested.lower()]
        else:
            fail(
                f"command column {cmd_col!r} not found in {csv_path}. CSV columns are: {fieldnames}\n"
                "Pass --cmd-col <column_name> if your command column has another name."
            )

        commands: List[CommandItem] = []
        # CSV row number starts at 2 because row 1 is the header.
        for csv_row, row in enumerate(reader, start=2):
            raw = row.get(actual_cmd_col, "")
            command = "" if raw is None else str(raw).strip()
            if not command:
                continue
            if command.lstrip().startswith("#"):
                continue

            local_index = len(commands) + 1
            metadata = {
                (k.strip() if k is not None else ""): ("" if v is None else str(v).strip())
                for k, v in row.items()
                if k is not None
            }
            # Reserved metadata keys. These are useful in --label-cols and in logs.
            metadata["__csv_file"] = str(csv_path)
            metadata["__csv_name"] = csv_path.name
            metadata["__csv_order"] = str(csv_order)
            metadata["__csv_local_index"] = str(local_index)
            item = CommandItem(
                index=start_index + len(commands),
                csv_file=str(csv_path),
                csv_name=csv_path.name,
                csv_order=csv_order,
                local_index=local_index,
                csv_row=csv_row,
                command=command,
                metadata=metadata,
            )
            commands.append(item)
            if limit is not None and len(commands) >= limit:
                break

    if not commands:
        fail(f"no runnable command found in column {cmd_col!r} for CSV file: {csv_path}")
    return commands


def parse_multiple_csv_commands(
    csv_paths: Sequence[Path],
    cmd_col: str = "command",
    *,
    limit: Optional[int] = None,
) -> Tuple[List[CommandItem], List[Tuple[Path, int]]]:
    """Parse several CSV files into one global queue.

    The CSV files are processed exactly in the order supplied by the user.
    Within each CSV, rows are processed from top to bottom. The optional --limit
    applies to the merged global queue, not separately to each CSV.
    """
    if not csv_paths:
        fail("at least one CSV file is required.")

    all_commands: List[CommandItem] = []
    summaries: List[Tuple[Path, int]] = []
    for csv_order, csv_path in enumerate(csv_paths, start=1):
        if limit is None:
            remaining: Optional[int] = None
        else:
            remaining = limit - len(all_commands)
            if remaining <= 0:
                break
        items = parse_csv_commands(
            csv_path,
            cmd_col,
            start_index=len(all_commands) + 1,
            csv_order=csv_order,
            limit=remaining,
        )
        all_commands.extend(items)
        summaries.append((csv_path, len(items)))

    if not all_commands:
        fail(f"no runnable command found in column {cmd_col!r} across all CSV files.")
    return all_commands, summaries

def list_panes(session: str) -> List[Pane]:
    out = run_tmux(["list-panes", "-s", "-t", session, "-F", PANE_FORMAT])
    panes: List[Pane] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 9:
            continue
        pane_id, sess, win_i, pane_i, win_name, tty, pid_s, cur_cmd, dead_s = parts
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        panes.append(Pane(
            pane_id=pane_id,
            session=sess,
            window_index=win_i,
            pane_index=pane_i,
            window_name=win_name,
            tty=tty,
            pane_pid=pid,
            current_command=cur_cmd,
            dead=(dead_s == "1"),
        ))

    def sort_key(p: Pane) -> Tuple[int, int, str]:
        wi = int(p.window_index) if p.window_index.isdigit() else 10**9
        pi = int(p.pane_index) if p.pane_index.isdigit() else 10**9
        return (wi, pi, p.pane_id)

    panes.sort(key=sort_key)
    return panes


def parse_csv_list(text: Optional[str]) -> Optional[Set[str]]:
    if not text:
        return None
    return {x.strip() for x in text.split(",") if x.strip()}


def filter_panes(
    panes: List[Pane],
    pane_filter: Optional[Set[str]],
    window_filter: Optional[Set[str]],
) -> List[Pane]:
    selected: List[Pane] = []
    for p in panes:
        if p.dead:
            continue
        if window_filter is not None:
            if p.window_index not in window_filter and p.window_name not in window_filter:
                continue
        if pane_filter is not None:
            accepted_names = {p.pane_id, p.target_short, p.target_full}
            if accepted_names.isdisjoint(pane_filter):
                continue
        selected.append(p)
    return selected


def filter_allowed_panes(panes: List[Pane], allowed_pane_ids: Set[str]) -> List[Pane]:
    """Return only the exact pane IDs selected at scheduler startup.

    This freezes the target set. If tmux pane indexes change after splits, joins,
    kills, or layout changes, the scheduler still talks only to the original pane
    IDs and never adopts a different pane with the same window.pane index.
    """
    return [p for p in panes if (not p.dead and p.pane_id in allowed_pane_ids)]


def read_proc_stat(pid: int) -> Optional[Tuple[int, int]]:
    """Return (process_group, terminal_foreground_process_group) for pid."""
    stat_path = Path("/proc") / str(pid) / "stat"
    try:
        content = stat_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    # /proc/<pid>/stat has "pid (comm) state ppid pgrp session tty_nr tpgid ...".
    # comm may contain spaces/parentheses, so split after the last ')'.
    right_paren = content.rfind(")")
    if right_paren < 0:
        return None
    rest = content[right_paren + 2:].split()
    if len(rest) < 6:
        return None
    try:
        pgrp = int(rest[2])
        tpgid = int(rest[5])
    except ValueError:
        return None
    return pgrp, tpgid


def basename_command(command: str) -> str:
    return os.path.basename((command or "").strip())


def pane_is_idle(pane: Pane, shell_names: Set[str], idle_detection: Optional[str] = None) -> bool:
    """Return True if pane appears to be sitting at an interactive shell prompt.

    strict: require tmux pane_current_command to be a shell and /proc tpgid to
        equal the shell process group. This is the previous safest rule.
    relaxed: require tmux pane_current_command to be a shell; if /proc is
        available and clearly shows a different foreground process group, treat
        the pane as busy. If /proc is unavailable or reports no foreground group,
        allow the pane. This is the fast-fill default.
    shell-only: require only tmux pane_current_command to be a shell. This
        maximizes filling but is less safe; use only on dedicated panes.
    """
    if pane.dead:
        return False

    cur = basename_command(pane.current_command)
    if cur not in shell_names:
        return False

    mode = (idle_detection or IDLE_DETECTION_MODE or "relaxed").strip().lower()
    if mode == "shell-only":
        return True

    proc_state = read_proc_stat(pane.pane_pid)
    if proc_state is None:
        return mode == "relaxed"

    shell_pgrp, foreground_pgrp = proc_state
    if foreground_pgrp == shell_pgrp:
        return True

    if mode == "relaxed" and foreground_pgrp in (-1, 0):
        return True

    return False


def get_fresh_pane(session: str, pane_id: str) -> Optional[Pane]:
    """Return an up-to-date Pane record by tmux pane id."""
    for p in list_panes(session):
        if p.pane_id == pane_id:
            return p
    return None


def verify_idle_before_send(
    *,
    session: str,
    pane_id: str,
    shell_names: Set[str],
    checks: int,
    interval: float,
) -> Tuple[bool, Optional[Pane], str]:
    """Require several fresh idle snapshots before tmux send-keys.

    A single tmux snapshot can race with a user manually starting a command.
    Multiple checks reduce that window and make the scheduler more conservative.
    """
    checks = max(1, int(checks))
    interval = max(0.0, float(interval))
    last: Optional[Pane] = None
    for i in range(checks):
        pane = get_fresh_pane(session, pane_id)
        last = pane
        if pane is None:
            return False, None, "pane disappeared"
        if pane.dead:
            return False, pane, "pane is dead"
        if not pane_is_idle(pane, shell_names):
            return False, pane, f"pane is busy: current={pane.current_command!r}"
        if i + 1 < checks:
            time.sleep(interval)
    return True, last, "idle"


def pane_state_label(pane: Pane, shell_names: Set[str]) -> str:
    return "IDLE" if pane_is_idle(pane, shell_names) else "BUSY"


def shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def unique_delimiter(*texts: str) -> str:
    base = "__TMUX_CSV_SCHEDULER_EOF__"
    delim = base
    i = 0
    while any(delim in t for t in texts):
        i += 1
        delim = f"{base}_{i}"
    return delim


def command_preview(command: str, max_chars: int) -> str:
    command = " ".join(command.split())
    if max_chars <= 0 or len(command) <= max_chars:
        return command
    return command[: max_chars - 3] + "..."


def label_for_item(item: CommandItem, label_cols: Sequence[str]) -> str:
    labels: List[str] = []
    for col in label_cols:
        col = col.strip()
        if not col:
            continue
        # case-insensitive lookup
        actual = None
        for k in item.metadata.keys():
            if k == col or k.lower() == col.lower():
                actual = k
                break
        if actual is None:
            continue
        val = item.metadata.get(actual, "")
        if val != "":
            labels.append(f"{actual}={val}")
    return " ".join(labels)



def safe_path_stem(name: str, max_chars: int = 80) -> str:
    """Return a filesystem-friendly short name for source CSV tags."""
    stem = Path(name).stem if name else "csv"
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._-") or "csv"
    if len(stem) > max_chars:
        stem = stem[:max_chars].rstrip("._-") or stem[:max_chars]
    return stem

def job_paths(log_dir: Path, item: CommandItem) -> Tuple[Path, Path, Path]:
    csv_tag = safe_path_stem(item.csv_name)
    tag = f"job_{item.index:05d}_csv{item.csv_order:03d}_{csv_tag}_row_{item.csv_row:05d}"
    scripts_dir = log_dir / "scripts"
    done_dir = log_dir / "done"
    job_logs_dir = log_dir / "job_logs"
    return (
        (scripts_dir / f"{tag}.sh").resolve(),
        (job_logs_dir / f"{tag}.log").resolve(),
        (done_dir / f"{tag}.exit").resolve(),
    )


def write_job_script(
    *,
    item: CommandItem,
    pane: Pane,
    log_dir: Path,
    prologue: str,
    workdir: Optional[str],
    label: str,
) -> Tuple[Path, Path, Path]:
    scripts_dir = log_dir / "scripts"
    done_dir = log_dir / "done"
    job_logs_dir = log_dir / "job_logs"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    done_dir.mkdir(parents=True, exist_ok=True)
    job_logs_dir.mkdir(parents=True, exist_ok=True)

    script_file, log_file, done_file = job_paths(log_dir, item)

    delimiter = unique_delimiter(item.command, prologue, label)

    workdir_line = ""
    if workdir:
        workdir_line = f"cd {shell_single_quote(workdir)} || exit 200\n"

    prologue_block = ""
    if prologue.strip():
        prologue_block = prologue.rstrip() + "\n"

    label_line = label if label else "(none)"

    script = f"""#!/usr/bin/env bash
# Auto-generated by tmux_csv_command_scheduler_fastfill.py.
# The script can be executed with 'bash script.sh' or sourced with '. script.sh'.
set +e

__tmux_sched_log={shell_single_quote(str(log_file))}
__tmux_sched_done={shell_single_quote(str(done_file))}
mkdir -p "$(dirname "$__tmux_sched_log")" "$(dirname "$__tmux_sched_done")"

{{
  echo "[tmux-scheduler] START job={item.index} csv={item.csv_name} csv_order={item.csv_order} local_index={item.local_index} csv_row={item.csv_row} pane={pane.pane_id} target={pane.target_full} time=$(date '+%Y-%m-%d %H:%M:%S')"
  echo "[tmux-scheduler] SOURCE_CSV {item.csv_file}"
  echo "[tmux-scheduler] LABEL {label_line}"
  echo "[tmux-scheduler] COMMAND:"
  cat <<'{delimiter}'
{item.command}
{delimiter}
  echo "[tmux-scheduler] OUTPUT BEGIN"
  (
    set +e
    export TMUX_CSV_JOB_ID={shell_single_quote(str(item.index))}
    export TMUX_CSV_SOURCE_FILE={shell_single_quote(item.csv_file)}
    export TMUX_CSV_SOURCE_NAME={shell_single_quote(item.csv_name)}
    export TMUX_CSV_SOURCE_ORDER={shell_single_quote(str(item.csv_order))}
    export TMUX_CSV_LOCAL_JOB_ID={shell_single_quote(str(item.local_index))}
    export TMUX_CSV_ROW={shell_single_quote(str(item.csv_row))}
    export TMUX_CSV_PANE={shell_single_quote(pane.pane_id)}
    export TMUX_CSV_LOG_FILE={shell_single_quote(str(log_file))}
{workdir_line}{prologue_block}{item.command}
  )
  __tmux_sched_ec=$?
  echo "[tmux-scheduler] OUTPUT END"
  echo "[tmux-scheduler] END job={item.index} exit=${{__tmux_sched_ec}} time=$(date '+%Y-%m-%d %H:%M:%S')"
  printf '%s\\n' "${{__tmux_sched_ec}}" > "$__tmux_sched_done"
  exit "${{__tmux_sched_ec}}"
}} 2>&1 | tee -a "$__tmux_sched_log"

# Read the real command exit code written by the wrapped block. This avoids
# relying on bash-specific PIPESTATUS when the file is sourced by another shell.
if [ -r "$__tmux_sched_done" ]; then
  __tmux_sched_ec=$(head -n 1 "$__tmux_sched_done" 2>/dev/null)
else
  __tmux_sched_ec=1
fi
case "$__tmux_sched_ec" in
  ''|*[!0-9]*) __tmux_sched_ec=1 ;;
esac
unset __tmux_sched_log __tmux_sched_done

# If this file was sourced into an interactive pane, return to the prompt without
# closing that pane. If it was executed as a standalone script, exit normally.
if (return 0 2>/dev/null); then
  return "$__tmux_sched_ec"
else
  exit "$__tmux_sched_ec"
fi
"""
    script_file.write_text(script, encoding="utf-8")
    script_file.chmod(0o755)
    return script_file, log_file, done_file


def send_command_to_pane(pane_id: str, command: str) -> None:
    """Send one generated command line to a tmux pane and execute it.

    Older versions used separate tmux actions, such as paste-buffer followed by
    send-keys C-m. On busy servers this could occasionally leave the generated
    wrapper command visible in the pane without executing it.

    This version avoids paste-buffer and uses a single tmux send-keys command to
    send the wrapper command text followed by the Enter key. The string sent
    here is not the CSV command itself; it is the generated wrapper invocation,
    for example `. /path/to/job_00001.sh` or `bash /path/to/job_00001.sh`.

    No Ctrl-C, Ctrl-D, Ctrl-Z, kill, or clear-screen operation is sent here.
    """
    if "\n" in command or "\r" in command:
        fail("internal dispatch command unexpectedly contains a newline")
    run_tmux(["send-keys", "-t", pane_id, "--", command, "Enter"], capture=False)

def parse_tmux_key_sequence(spec: str) -> List[str]:
    """Parse a comma-separated tmux send-keys sequence.

    The default sequence clears an interactive shell's current input line without
    sending Enter or Ctrl-C:

      C-e,C-u,C-a,C-k

    C-e moves to end of line, C-u kills text before the cursor, C-a moves to
    beginning of line, and C-k kills text after the cursor. In ordinary bash,
    zsh, fish, and many readline-like shells this removes a partially typed
    command line while leaving foreground jobs untouched because this function
    is called only after the pane has passed idle checks.
    """
    keys = [x.strip() for x in spec.split(",") if x.strip()]
    if not keys:
        fail("--clear-input-keys produced an empty key sequence.")

    # Do not allow keys that could execute, interrupt, suspend, log out, or send
    # a hard EOF. This keeps the cleanup step non-interruptive.
    forbidden = {
        "c-c", "ctrl-c",
        "c-d", "ctrl-d",
        "c-m", "enter", "return", "nenter",
        "c-j",
        "c-z", "ctrl-z",
        "c-\\", "ctrl-\\",
    }
    bad = [k for k in keys if k.lower() in forbidden]
    if bad:
        fail(
            "--clear-input-keys contains unsafe key(s): "
            + ", ".join(bad)
            + ". Do not use Enter, Ctrl-C, Ctrl-D, Ctrl-Z, or Ctrl-\\ here."
        )
    return keys


def clear_pane_input_line(pane_id: str, keys: Sequence[str]) -> None:
    """Clear only the current shell input line in a tmux pane.

    This does not press Enter and does not send Ctrl-C. It is meant to remove
    accidental characters already typed at an idle shell prompt before the
    scheduler sends the generated job command.
    """
    if not keys:
        return
    run_tmux(["send-keys", "-t", pane_id, *keys], capture=False)


def read_exit_file(done_file: Path) -> Optional[int]:
    try:
        txt = done_file.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not txt:
        return None
    try:
        return int(txt.splitlines()[0].strip())
    except ValueError:
        return None


def append_csv_row(path: Path, row: Dict[str, str], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in fieldnames})


EVENT_FIELDS = [
    "time",
    "event",
    "job_id",
    "total_jobs",
    "csv_file",
    "csv_name",
    "csv_order",
    "csv_local_index",
    "csv_row",
    "pane_id",
    "target",
    "exit_code",
    "duration_sec",
    "completed",
    "success",
    "failed",
    "running",
    "pending",
    "label",
    "log_file",
    "script_file",
    "command",
]


def append_event(
    log_dir: Path,
    *,
    event: str,
    job: Optional[RunningJob] = None,
    item: Optional[CommandItem] = None,
    total_jobs: int,
    exit_code: Optional[int] = None,
    duration_sec: Optional[float] = None,
    completed: int = 0,
    success: int = 0,
    failed: int = 0,
    running: int = 0,
    pending: int = 0,
    label: str = "",
    command: str = "",
    pane_id: str = "",
    target: str = "",
    log_file: str = "",
    script_file: str = "",
) -> None:
    if job is not None:
        item = job.command_item
        pane_id = job.pane_id
        target = job.target_full
        log_file = str(job.log_file)
        script_file = str(job.script_file)
        command = item.command
    if item is not None:
        command = command or item.command
    row = {
        "time": now_str(),
        "event": event,
        "job_id": str(item.index if item else ""),
        "total_jobs": str(total_jobs),
        "csv_file": str(item.csv_file if item else ""),
        "csv_name": str(item.csv_name if item else ""),
        "csv_order": str(item.csv_order if item else ""),
        "csv_local_index": str(item.local_index if item else ""),
        "csv_row": str(item.csv_row if item else ""),
        "pane_id": pane_id,
        "target": target,
        "exit_code": "" if exit_code is None else str(exit_code),
        "duration_sec": "" if duration_sec is None else f"{duration_sec:.1f}",
        "completed": str(completed),
        "success": str(success),
        "failed": str(failed),
        "running": str(running),
        "pending": str(pending),
        "label": label,
        "log_file": log_file,
        "script_file": script_file,
        "command": command,
    }
    append_csv_row(log_dir / "scheduler_events.csv", row, EVENT_FIELDS)


def running_state_path(log_dir: Path) -> Path:
    return log_dir / "state" / "running_jobs.json"


def write_running_state(log_dir: Path, running: Dict[str, RunningJob]) -> None:
    path = running_state_path(log_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "updated_at": now_str(),
        "running": [
            {
                "job_id": job.command_item.index,
                "csv_file": job.command_item.csv_file,
                "csv_name": job.command_item.csv_name,
                "csv_order": job.command_item.csv_order,
                "csv_local_index": job.command_item.local_index,
                "csv_row": job.command_item.csv_row,
                "command": job.command_item.command,
                "metadata": job.command_item.metadata,
                "pane_id": job.pane_id,
                "target_full": job.target_full,
                "log_file": str(job.log_file),
                "done_file": str(job.done_file),
                "script_file": str(job.script_file),
                "start_time": job.start_time,
                "start_epoch": job.start_epoch,
                "recovered": job.recovered,
            }
            for job in running.values()
        ],
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_running_state(log_dir: Path) -> List[Dict[str, object]]:
    path = running_state_path(log_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = data.get("running", [])
    if isinstance(items, list):
        return [x for x in items if isinstance(x, dict)]
    return []


def done_file_for(log_dir: Path, item: CommandItem) -> Path:
    _, _, done_file = job_paths(log_dir, item)
    return done_file


def count_done_and_failed(log_dir: Path, jobs: Sequence[CommandItem]) -> Tuple[int, int, int]:
    done = 0
    success = 0
    failed = 0
    for item in jobs:
        ec = read_exit_file(done_file_for(log_dir, item))
        if ec is None:
            continue
        done += 1
        if ec == 0:
            success += 1
        else:
            failed += 1
    return done, success, failed


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Safely dispatch commands from one or more CSV 'command' columns to idle tmux panes.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("csv_files", nargs="+", help="One or more CSV files containing a command column. Files are processed in the order given here.")
    p.add_argument("--session", "-s", help="tmux session name. If omitted, use current session or the only existing session.")
    p.add_argument("--cmd-col", default="command",
                   help="CSV column containing simulation commands.")
    p.add_argument("--panes", default=None,
                   help="Comma-separated target panes that are allowed to receive jobs, e.g. '0.0,0.1,%%3'. For safety, prefer stable pane ids like %%3.")
    p.add_argument("--windows", default=None,
                   help="Optional window indexes or window names used only to narrow selection. For safety, --panes is still required unless --allow-all-panes is passed.")
    p.add_argument("--allow-all-panes", action="store_true",
                   help="Allow using every pane in the selected session/window. Without this, you must pass --panes.")
    p.add_argument("--include-current-pane", action="store_true",
                   help="Allow using the pane where the scheduler itself is running. By default, TMUX_PANE is excluded when available.")
    p.add_argument("--initial-busy-policy", choices=["wait", "exclude"], default="wait",
                   help="What to do with panes that are busy when the scheduler starts. Default 'wait' protects them while busy, then uses them after they naturally return to shell. 'exclude' is more conservative and never uses them in this scheduler run.")
    p.add_argument("--no-strict-presend-check", action="store_true",
                   help="Disable the final fresh idle check immediately before sending a command. Leave this unset for maximum safety.")
    p.add_argument("--idle-checks", type=int, default=1,
                   help="Number of consecutive fresh idle checks required before sending a job to a pane. Fast-fill default is 1 to reduce idle gaps.")
    p.add_argument("--idle-check-interval", type=float, default=0.1,
                   help="Seconds between consecutive pre-send idle checks.")
    p.add_argument("--no-clear-input-before-dispatch", action="store_true",
                   help="Disable the default cleanup that clears an idle shell's current input line before pasting a job command. The cleanup uses non-interruptive keys and never sends Ctrl-C.")
    p.add_argument("--clear-input-keys", default="C-e,C-u,C-a,C-k",
                   help="Comma-separated tmux send-keys sequence used to clear the current shell input line before dispatch. Unsafe keys such as Enter, Ctrl-C, Ctrl-D and Ctrl-Z are rejected.")
    p.add_argument("--clear-input-settle", type=float, default=0.02,
                   help="Seconds to wait after clearing the input line before the final post-clear idle check and dispatch.")
    p.add_argument("--log-dir", default=None,
                   help="Directory for scheduler logs, generated scripts, per-job logs, done files, and state.")
    p.add_argument("--poll", type=float, default=1.0,
                   help="Polling interval in seconds. Fast-fill default is 1 second.")
    p.add_argument("--status-interval", type=float, default=10.0,
                   help="Print one detailed status block every N seconds. Use 0 to disable periodic status.")
    p.add_argument("--start-at", type=int, default=1,
                   help="1-based job id after filtering blank/comment command rows.")
    p.add_argument("--limit", type=int, default=None,
                   help="Only load the first N runnable commands from the merged CSV queue. Useful for a small test.")
    p.add_argument("--resume", action="store_true",
                   help="Skip jobs whose done files already exist in --log-dir and recover tracked running jobs.")
    p.add_argument("--file-barrier", action="store_true",
                   help=argparse.SUPPRESS)  # Deprecated no-op in fast-fill version.
    p.add_argument("--dispatch-mode", choices=["source", "bash"], default="source",
                   help="'source' runs '. generated_script.sh' inside the existing pane shell; 'bash' runs 'bash generated_script.sh'. Source mode can use shell functions already defined in the pane.")
    p.add_argument("--prologue", default="",
                   help="Shell code inserted before every command, e.g. 'source ~/.bashrc; conda activate myenv'.")
    p.add_argument("--workdir", default=None,
                   help="Directory to cd into before every command. If omitted, each pane's current directory is used.")
    p.add_argument("--label-cols", default="stage,case,total_arrival_rate,K,seed",
                   help="Comma-separated CSV columns printed as short labels in progress messages.")
    p.add_argument("--idle-detection", choices=["strict", "relaxed", "shell-only"], default="relaxed",
                   help="How to decide whether a pane is idle. strict is safest; relaxed is the fast-fill default; shell-only maximizes filling but is less safe.")
    p.add_argument("--shells", default=",".join(sorted(DEFAULT_SHELLS)),
                   help="Comma-separated command names treated as idle shells.")
    p.add_argument("--print-command-max", type=int, default=180,
                   help="Maximum command preview length in scheduler progress output.")
    p.add_argument("--stop-on-fail", action="store_true",
                   help="Do not dispatch new jobs after the first non-zero exit code. Already running jobs are still monitored.")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse CSV file(s) and panes, then show what would be used without sending commands.")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    global IDLE_DETECTION_MODE
    args = build_arg_parser().parse_args(argv)
    IDLE_DETECTION_MODE = args.idle_detection

    if args.start_at < 1:
        fail("--start-at must be >= 1")
    if args.limit is not None and args.limit < 1:
        fail("--limit must be >= 1 when provided.")
    if args.idle_checks < 1:
        fail("--idle-checks must be >= 1")
    if args.idle_check_interval < 0:
        fail("--idle-check-interval must be >= 0")
    if args.clear_input_settle < 0:
        fail("--clear-input-settle must be >= 0")

    clear_input_before_dispatch = not args.no_clear_input_before_dispatch
    clear_input_keys = parse_tmux_key_sequence(args.clear_input_keys) if clear_input_before_dispatch else []

    csv_paths = [Path(x).expanduser().resolve() for x in args.csv_files]
    commands, csv_summaries = parse_multiple_csv_commands(csv_paths, args.cmd_col, limit=args.limit)
    if args.start_at > len(commands):
        fail(f"--start-at={args.start_at} is beyond available commands ({len(commands)}).")

    scheduled_jobs = commands[args.start_at - 1:]
    total_jobs = len(scheduled_jobs)
    final_job_index = commands[-1].index

    session = resolve_session(args.session)
    pane_filter = parse_csv_list(args.panes)
    window_filter = parse_csv_list(args.windows)

    if pane_filter is None and not args.allow_all_panes:
        fail(
            "safety stop: --panes is required by default. "
            "Pass --panes with only the pane IDs you allow this scheduler to use, "
            "for example --panes '%3,%4,%5'. Use --allow-all-panes only on a dedicated tmux session/window."
        )

    panes_all = list_panes(session)
    panes = filter_panes(panes_all, pane_filter, window_filter)

    current_scheduler_pane = os.environ.get("TMUX_PANE", "").strip()
    if current_scheduler_pane and not args.include_current_pane:
        panes = [p for p in panes if p.pane_id != current_scheduler_pane]

    if not panes:
        fail("no target panes selected. Check --session, --windows, --panes, or --include-current-pane if you intentionally want to use the scheduler pane.")

    # Freeze the exact pane IDs chosen at startup. After this point, the scheduler
    # never adopts newly created panes or a different pane that later reuses a
    # window.pane index such as 0.1.
    allowed_pane_ids: Set[str] = {p.pane_id for p in panes}

    if args.log_dir:
        log_dir = Path(args.log_dir).expanduser().resolve()
    else:
        if len(csv_paths) == 1:
            log_name = f"tmux_csv_logs_{csv_paths[0].stem}_{timestamp_for_path()}"
        else:
            log_name = f"tmux_csv_logs_multi_{len(csv_paths)}files_{timestamp_for_path()}"
        log_dir = (Path.cwd() / log_name).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    label_cols = [x.strip() for x in args.label_cols.split(",") if x.strip()]
    shell_names = {x.strip() for x in args.shells.split(",") if x.strip()}
    if not shell_names:
        shell_names = set(DEFAULT_SHELLS)

    initial_busy_panes: Set[str] = {p.pane_id for p in panes if not pane_is_idle(p, shell_names)}
    initial_busy_targets: Dict[str, str] = {p.pane_id: p.target_full for p in panes if p.pane_id in initial_busy_panes}
    excluded_initial_busy: Set[str] = set(initial_busy_panes) if args.initial_busy_policy == "exclude" else set()
    protected_initial_busy: Set[str] = set(initial_busy_panes) if args.initial_busy_policy == "wait" else set()

    logger = SchedulerLogger(log_dir / "scheduler_progress.log")

    try:
        logger.log(f"[{now_str()}] CSV files: {len(csv_paths)}")
        for i, (path, n_items) in enumerate(csv_summaries, start=1):
            logger.log(f"  CSV[{i}] commands={n_items}: {path}")
        logger.log(f"[{now_str()}] command column: {args.cmd_col!r}")
        logger.log(f"[{now_str()}] runnable jobs loaded after merge: {len(commands)}; scheduling from global job {args.start_at}; total to schedule: {total_jobs}; file_barrier=disabled_fast_fill")
        logger.log(f"[{now_str()}] tmux session: {session}; selected panes: {len(panes)}; frozen pane IDs: {','.join(sorted(allowed_pane_ids))}; log_dir: {log_dir}")
        logger.log(f"[{now_str()}] dispatch mode: {args.dispatch_mode}")
        logger.log(f"[{now_str()}] tmux send method: single tmux send-keys call with generated command plus Enter; no paste-buffer")
        if getattr(args, "file_barrier", False):
            logger.log(f"[{now_str()}] fast-fill: --file-barrier was provided but is ignored in this version; later CSV jobs may overlap earlier CSV jobs once their turn reaches the queue head.")
        logger.log(f"[{now_str()}] safety: explicit --panes required={not args.allow_all_panes}; initial_busy_policy={args.initial_busy_policy}; idle_detection={args.idle_detection}; strict_presend_check={not args.no_strict_presend_check}; idle_checks={args.idle_checks}x{args.idle_check_interval}s; clear_input_before_dispatch={clear_input_before_dispatch}; clear_input_keys={','.join(clear_input_keys) if clear_input_keys else '(disabled)'}")
        if current_scheduler_pane and not args.include_current_pane:
            logger.log(f"[{now_str()}] safety: scheduler pane excluded: {current_scheduler_pane}")
        logger.log(f"[{now_str()}] safety: this script never sends Ctrl-C or kill. It clears the current input line and then sends one generated command line plus Enter to panes judged IDLE; fast-fill mode uses shorter idle checks.")
        if args.workdir:
            logger.log(f"[{now_str()}] workdir for every job: {args.workdir}")
        if args.prologue.strip():
            logger.log(f"[{now_str()}] prologue is enabled.")

        logger.log("")
        logger.log("Selected tmux panes:")
        for p in panes:
            state = pane_state_label(p, shell_names)
            safety_note = ""
            if p.pane_id in excluded_initial_busy:
                safety_note = " excluded_initial_busy"
            elif p.pane_id in protected_initial_busy:
                safety_note = " protected_until_idle"
            logger.log(
                f"  {p.target_full:<18} {p.pane_id:<6} tty={p.tty:<12} "
                f"pid={p.pane_pid:<8} current={p.current_command:<16} state={state}{safety_note}"
            )

        if initial_busy_panes:
            logger.log("")
            logger.log(
                f"[{now_str()}] safety: {len(initial_busy_panes)} selected pane(s) are BUSY at startup. "
                f"They will receive no command while busy."
            )
            if args.initial_busy_policy == "wait":
                logger.log("  policy=wait: a protected pane becomes eligible only after it naturally returns to shell.")
            else:
                logger.log("  policy=exclude: these initially busy panes will not be used by this scheduler run.")

        if args.initial_busy_policy == "exclude" and len(excluded_initial_busy) == len(panes):
            logger.log("")
            logger.log(
                f"[{now_str()}] safety stop: all selected panes are BUSY at startup and "
                "--initial-busy-policy=exclude is active, so no pane will be used."
            )
            logger.log("Create/select at least one idle pane, or rerun with --initial-busy-policy wait if you explicitly want to use those panes after they finish.")
            if not args.dry_run:
                return 3

        logger.log("")
        logger.log("First commands:")
        for item in scheduled_jobs[: min(10, len(scheduled_jobs))]:
            label = label_for_item(item, label_cols)
            prefix = f"  job {item.index:05d}/{final_job_index:05d} csv={item.csv_name} local={item.local_index:05d} csv_row={item.csv_row}"
            if label:
                prefix += f" [{label}]"
            logger.log(f"{prefix}: {command_preview(item.command, args.print_command_max)}")
        if len(scheduled_jobs) > 10:
            logger.log(f"  ... {len(scheduled_jobs) - 10} more jobs not shown")

        if args.dry_run:
            logger.log("")
            logger.log(f"[{now_str()}] dry-run finished. No command was sent to tmux.")
            return 0

        if excluded_initial_busy and len(excluded_initial_busy) == len(allowed_pane_ids):
            fail(
                "all selected panes were busy at startup. With the safe default "
                "--initial-busy-policy exclude, none of them will receive jobs. "
                "Open/select at least one idle pane, or explicitly pass "
                "--initial-busy-policy wait if you intend to reuse them after they finish."
            )

        if args.dispatch_mode == "source":
            logger.log("")
            logger.log(
                "Note: source mode sends '. generated_script.sh' to each selected pane. "
                "This usually preserves shell functions already defined in that pane, "
                "for example a function named run_exact_point. Because it runs inside "
                "the pane's shell, prologue commands such as conda activation or cd "
                "may leave that selected pane's shell environment changed after the job."
            )

        # Recover running jobs if requested.
        running: Dict[str, RunningJob] = {}
        claimed_job_ids: Set[int] = set()
        panes_current = [p for p in filter_allowed_panes(list_panes(session), allowed_pane_ids) if p.pane_id not in excluded_initial_busy]
        pane_by_id = {p.pane_id: p for p in panes_current}
        if args.resume:
            for rec in load_running_state(log_dir):
                try:
                    job_id = int(rec.get("job_id", -1))
                except Exception:
                    continue
                item = next((x for x in scheduled_jobs if x.index == job_id), None)
                if item is None:
                    continue
                done_file = Path(str(rec.get("done_file", done_file_for(log_dir, item)))).expanduser()
                if read_exit_file(done_file) is not None:
                    claimed_job_ids.add(item.index)
                    continue
                pane_id = str(rec.get("pane_id", ""))
                pane = pane_by_id.get(pane_id)
                if pane is None:
                    logger.log(f"[{now_str()}] resume warning: job {item.index:05d} csv={item.csv_name} local={item.local_index:05d} had pane {pane_id}, but pane no longer exists; it may be requeued.")
                    continue
                if pane_is_idle(pane, shell_names):
                    logger.log(f"[{now_str()}] resume warning: job {item.index:05d} csv={item.csv_name} local={item.local_index:05d} had pane {pane_id}, but pane is idle and no done file exists; it may be requeued.")
                    continue
                script_file = Path(str(rec.get("script_file", job_paths(log_dir, item)[0]))).expanduser()
                log_file = Path(str(rec.get("log_file", job_paths(log_dir, item)[1]))).expanduser()
                start_epoch = rec.get("start_epoch", time.time())
                try:
                    start_epoch_f = float(start_epoch)
                except Exception:
                    start_epoch_f = time.time()
                job = RunningJob(
                    command_item=item,
                    pane_id=pane_id,
                    target_full=str(rec.get("target_full", pane.target_full)),
                    log_file=log_file,
                    done_file=done_file,
                    script_file=script_file,
                    start_time=str(rec.get("start_time", now_str())),
                    start_epoch=start_epoch_f,
                    recovered=True,
                )
                running[pane_id] = job
                claimed_job_ids.add(item.index)
                logger.log(f"[{now_str()}] resume: recovered running job {item.index:05d} csv={item.csv_name} local={item.local_index:05d} on {pane.target_full} {pane.pane_id}; log={log_file}")

        pending: Deque[CommandItem] = deque(scheduled_jobs)
        launched = 0
        observed_success: Set[int] = set()
        observed_failed: Set[int] = set()
        observed_completed: Set[int] = set()
        stop_new_jobs = False
        last_status_print = 0.0
        exit_code_final = 0

        logger.log("")
        logger.log(f"[{now_str()}] scheduler started. Press Ctrl-C to stop only the scheduler; jobs already running inside tmux are not killed.")

        while True:
            panes_current = [p for p in filter_allowed_panes(list_panes(session), allowed_pane_ids) if p.pane_id not in excluded_initial_busy]
            pane_by_id = {p.pane_id: p for p in panes_current}

            # Finalize running jobs whose wrapper has written the done file and whose pane returned to idle.
            for pane_id, job in list(running.items()):
                pane = pane_by_id.get(pane_id)
                ec = read_exit_file(job.done_file)

                if pane is None or (pane is not None and pane.dead):
                    if ec is None:
                        logger.log(f"[{now_str()}] WARNING: pane disappeared/dead before job finished: job={job.command_item.index:05d} pane={pane_id} log={job.log_file}")
                        append_event(
                            log_dir,
                            event="pane_lost",
                            job=job,
                            total_jobs=total_jobs,
                            completed=len(observed_completed),
                            success=len(observed_success),
                            failed=len(observed_failed),
                            running=len(running),
                            pending=len(pending),
                            label=label_for_item(job.command_item, label_cols),
                        )
                        del running[pane_id]
                        write_running_state(log_dir, running)
                    else:
                        duration = time.time() - job.start_epoch
                        observed_completed.add(job.command_item.index)
                        if ec == 0:
                            observed_success.add(job.command_item.index)
                        else:
                            observed_failed.add(job.command_item.index)
                            exit_code_final = 2
                            stop_new_jobs = stop_new_jobs or args.stop_on_fail
                        logger.log(
                            f"[{now_str()}] DONE job {job.command_item.index:05d}/{final_job_index:05d} "
                            f"csv={job.command_item.csv_name} local={job.command_item.local_index:05d} row={job.command_item.csv_row} pane={pane_id} exit={ec} elapsed={seconds_to_hms(duration)} "
                            f"log={job.log_file}"
                        )
                        append_event(
                            log_dir,
                            event="finish",
                            job=job,
                            total_jobs=total_jobs,
                            exit_code=ec,
                            duration_sec=duration,
                            completed=len(observed_completed),
                            success=len(observed_success),
                            failed=len(observed_failed),
                            running=len(running) - 1,
                            pending=len(pending),
                            label=label_for_item(job.command_item, label_cols),
                        )
                        del running[pane_id]
                        write_running_state(log_dir, running)
                    continue

                if ec is not None and pane_is_idle(pane, shell_names):
                    duration = time.time() - job.start_epoch
                    observed_completed.add(job.command_item.index)
                    if ec == 0:
                        observed_success.add(job.command_item.index)
                    else:
                        observed_failed.add(job.command_item.index)
                        exit_code_final = 2
                        stop_new_jobs = stop_new_jobs or args.stop_on_fail

                    logger.log(
                        f"[{now_str()}] DONE job {job.command_item.index:05d}/{final_job_index:05d} "
                        f"csv={job.command_item.csv_name} local={job.command_item.local_index:05d} row={job.command_item.csv_row} pane={pane.target_full} {pane.pane_id} "
                        f"exit={ec} elapsed={seconds_to_hms(duration)} "
                        f"completed={len(observed_completed)}/{total_jobs} failed={len(observed_failed)}"
                    )
                    append_event(
                        log_dir,
                        event="finish",
                        job=job,
                        total_jobs=total_jobs,
                        exit_code=ec,
                        duration_sec=duration,
                        completed=len(observed_completed),
                        success=len(observed_success),
                        failed=len(observed_failed),
                        running=len(running) - 1,
                        pending=len(pending),
                        label=label_for_item(job.command_item, label_cols),
                    )
                    del running[pane_id]
                    write_running_state(log_dir, running)

            # Remove already-done or recovered jobs from the front of the pending queue.
            while pending:
                head = pending[0]
                if args.resume and read_exit_file(done_file_for(log_dir, head)) is not None:
                    ec = read_exit_file(done_file_for(log_dir, head))
                    pending.popleft()
                    observed_completed.add(head.index)
                    if ec == 0:
                        observed_success.add(head.index)
                    else:
                        observed_failed.add(head.index)
                        exit_code_final = 2
                    logger.log(f"[{now_str()}] resume: skip completed job {head.index:05d} csv={head.csv_name} local={head.local_index:05d} row={head.csv_row} exit={ec}")
                    continue
                if head.index in claimed_job_ids:
                    pending.popleft()
                    continue
                break

            # Assign new jobs to idle panes, preserving CSV order.  Safety rules here are deliberate:
            #   1) never send to panes excluded because they were busy at startup;
            #   2) for protected startup-busy panes, wait until they are naturally idle;
            #   3) refresh the pane immediately before sending, then send only if still idle.
            if not stop_new_jobs:
                for pane in panes_current:
                    if not pending:
                        break
                    if pane.pane_id in running:
                        continue
                    if pane.pane_id in excluded_initial_busy:
                        continue

                    if pane.pane_id in protected_initial_busy:
                        if pane_is_idle(pane, shell_names):
                            protected_initial_busy.remove(pane.pane_id)
                            logger.log(
                                f"[{now_str()}] PANE AVAILABLE after initial busy: "
                                f"{pane.target_full} {pane.pane_id}. It may now receive a queued job."
                            )
                        else:
                            # Explicitly protect panes that were already running something when
                            # this scheduler started. No send-keys occurs here.
                            continue

                    if not pane_is_idle(pane, shell_names):
                        continue

                    # Fresh pre-send check. This reduces the race window if a user manually
                    # starts something in the pane after the last polling snapshot.
                    dispatch_pane = pane
                    if not args.no_strict_presend_check:
                        ok, fresh, reason = verify_idle_before_send(
                            session=session,
                            pane_id=pane.pane_id,
                            shell_names=shell_names,
                            checks=args.idle_checks,
                            interval=args.idle_check_interval,
                        )
                        if not ok or fresh is None:
                            logger.log(
                                f"[{now_str()}] SKIP pane not idle before dispatch: "
                                f"{pane.target_full} {pane.pane_id}; reason={reason}; no command sent."
                            )
                            continue
                        dispatch_pane = fresh

                    # Keep skipping jobs already completed by a previous run.
                    while pending:
                        head = pending[0]
                        if args.resume and read_exit_file(done_file_for(log_dir, head)) is not None:
                            ec = read_exit_file(done_file_for(log_dir, head))
                            pending.popleft()
                            observed_completed.add(head.index)
                            if ec == 0:
                                observed_success.add(head.index)
                            else:
                                observed_failed.add(head.index)
                                exit_code_final = 2
                            logger.log(f"[{now_str()}] resume: skip completed job {head.index:05d} csv={head.csv_name} local={head.local_index:05d} row={head.csv_row} exit={ec}")
                            continue
                        if head.index in claimed_job_ids:
                            pending.popleft()
                            continue
                        break

                    if not pending:
                        break

                    # Fast-fill version: no file barrier. Multiple CSV files are still
                    # queued in the order supplied on the command line, but later CSV jobs
                    # may start as soon as they reach the head of the global queue and any
                    # pane is eligible. This avoids leaving panes idle at CSV boundaries.
                    item = pending.popleft()
                    # Avoid reading an old done file as a fresh completion when not resuming.
                    old_done = done_file_for(log_dir, item)
                    if old_done.exists() and not args.resume:
                        try:
                            old_done.unlink()
                        except OSError:
                            pass

                    label = label_for_item(item, label_cols)
                    script_file, log_file, done_file = write_job_script(
                        item=item,
                        pane=dispatch_pane,
                        log_dir=log_dir,
                        prologue=args.prologue,
                        workdir=args.workdir,
                        label=label,
                    )
                    if args.dispatch_mode == "source":
                        send_line = f". {shlex.quote(str(script_file))}"
                    else:
                        send_line = f"bash {shlex.quote(str(script_file))}"

                    # Final check after generating the script and immediately before tmux send-keys.
                    if not args.no_strict_presend_check:
                        ok, fresh, reason = verify_idle_before_send(
                            session=session,
                            pane_id=dispatch_pane.pane_id,
                            shell_names=shell_names,
                            checks=args.idle_checks,
                            interval=args.idle_check_interval,
                        )
                        if not ok or fresh is None:
                            pending.appendleft(item)
                            logger.log(
                                f"[{now_str()}] SKIP_SEND pane not idle at final check: "
                                f"{dispatch_pane.target_full} {dispatch_pane.pane_id}; reason={reason}; "
                                "job requeued; no command sent."
                            )
                            continue
                        dispatch_pane = fresh

                    # Clear any partially typed shell input before pasting the scheduler command.
                    # This is deliberately done only after the pane has passed the final idle check.
                    # It does not send Ctrl-C and does not press Enter.
                    if clear_input_before_dispatch:
                        clear_pane_input_line(dispatch_pane.pane_id, clear_input_keys)
                        if args.clear_input_settle > 0:
                            time.sleep(args.clear_input_settle)

                        # One more conservative check after clearing the line. If the pane became
                        # busy for any reason, requeue the job and do not send the command.
                        if not args.no_strict_presend_check:
                            ok, fresh, reason = verify_idle_before_send(
                                session=session,
                                pane_id=dispatch_pane.pane_id,
                                shell_names=shell_names,
                                checks=1,
                                interval=0.0,
                            )
                            if not ok or fresh is None:
                                pending.appendleft(item)
                                logger.log(
                                    f"[{now_str()}] SKIP_SEND pane not idle after input-line cleanup: "
                                    f"{dispatch_pane.target_full} {dispatch_pane.pane_id}; reason={reason}; "
                                    "job requeued; no command sent."
                                )
                                continue
                            dispatch_pane = fresh

                    send_command_to_pane(dispatch_pane.pane_id, send_line)
                    job = RunningJob(
                        command_item=item,
                        pane_id=dispatch_pane.pane_id,
                        target_full=dispatch_pane.target_full,
                        log_file=log_file,
                        done_file=done_file,
                        script_file=script_file,
                        start_time=now_str(),
                        start_epoch=time.time(),
                    )
                    running[dispatch_pane.pane_id] = job
                    claimed_job_ids.add(item.index)
                    launched += 1
                    write_running_state(log_dir, running)

                    logger.log(
                        f"[{now_str()}] DISPATCH job {item.index:05d}/{final_job_index:05d} "
                        f"csv={item.csv_name} local={item.local_index:05d} row={item.csv_row} -> {dispatch_pane.target_full} {dispatch_pane.pane_id} "
                        f"running={len(running)} pending={len(pending)}"
                    )
                    if label:
                        logger.log(f"  label: {label}")
                    logger.log(f"  cmd: {command_preview(item.command, args.print_command_max)}")
                    logger.log(f"  log: {log_file}")
                    append_event(
                        log_dir,
                        event="dispatch",
                        job=job,
                        total_jobs=total_jobs,
                        completed=len(observed_completed),
                        success=len(observed_success),
                        failed=len(observed_failed),
                        running=len(running),
                        pending=len(pending),
                        label=label,
                    )
            elif args.stop_on_fail and pending:
                # Do not spam this line every loop.
                pass

            # Termination.
            if not pending and not running:
                all_done, all_success, all_failed = count_done_and_failed(log_dir, scheduled_jobs)
                logger.log("")
                logger.log(
                    f"[{now_str()}] ALL FINISHED. total={total_jobs} done_files={all_done} "
                    f"success={all_success} failed={all_failed} launched_this_run={launched} log_dir={log_dir}"
                )
                if all_failed > 0:
                    exit_code_final = 2
                return exit_code_final

            # Periodic status.
            now = time.time()
            if args.status_interval and now - last_status_print >= args.status_interval:
                all_done, all_success, all_failed = count_done_and_failed(log_dir, scheduled_jobs)
                idle_count = sum(
                    1 for p in panes_current
                    if p.pane_id not in running and pane_is_idle(p, shell_names)
                )
                logger.log("")
                logger.log(
                    f"[{now_str()}] STATUS total={total_jobs} done={all_done} success={all_success} failed={all_failed} "
                    f"running={len(running)} pending={len(pending)} idle_panes={idle_count} "
                    f"protected_initial_busy={len(protected_initial_busy)} excluded_initial_busy={len(excluded_initial_busy)} "
                    f"stop_new_jobs={stop_new_jobs}"
                )
                if running:
                    for job in sorted(running.values(), key=lambda x: x.command_item.index):
                        elapsed = seconds_to_hms(now - job.start_epoch)
                        rec = " recovered" if job.recovered else ""
                        label = label_for_item(job.command_item, label_cols)
                        label_text = f" [{label}]" if label else ""
                        logger.log(
                            f"  RUNNING{rec} job={job.command_item.index:05d} csv={job.command_item.csv_name} local={job.command_item.local_index:05d} row={job.command_item.csv_row} "
                            f"pane={job.pane_id} elapsed={elapsed}{label_text}"
                        )
                if pending:
                    nxt = pending[0]
                    label = label_for_item(nxt, label_cols)
                    label_text = f" [{label}]" if label else ""
                    logger.log(
                        f"  NEXT job={nxt.index:05d} csv={nxt.csv_name} local={nxt.local_index:05d} row={nxt.csv_row}{label_text}: "
                        f"{command_preview(nxt.command, args.print_command_max)}"
                    )
                logger.log("")
                last_status_print = now

            time.sleep(max(args.poll, 0.2))

    except KeyboardInterrupt:
        logger.log("")
        logger.log(f"[{now_str()}] scheduler stopped by user. Running tmux jobs were not killed.")
        if running:
            logger.log("Still tracked running jobs:")
            for job in running.values():
                logger.log(f"  job={job.command_item.index:05d} csv={job.command_item.csv_name} local={job.command_item.local_index:05d} row={job.command_item.csv_row} pane={job.pane_id} log={job.log_file}")
            write_running_state(log_dir, running)
            logger.log(f"Use --resume with the same --log-dir to continue tracking them later: {log_dir}")
        return 130
    finally:
        logger.close()


if __name__ == "__main__":
    raise SystemExit(main())
