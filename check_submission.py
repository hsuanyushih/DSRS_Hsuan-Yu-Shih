#!/usr/bin/env python3
"""Check that we will be able to read your submission.

    python check_submission.py

Run this before you submit. It verifies the things that make a submission
unreadable — a missing collaborator, a public repo, an unpushed commit — plus the
artifacts we expect to find.

None of this touches your code's correctness. Use `python verify.py` for that.

FROZEN FILE.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

BOT = "dsrsBOT"
DEADLINE = "Monday, August 24, 2026 at 11:59 AM US Central"

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

REQUIRED = [
    ("output/holdings.parquet", "Chapter 3 · Structure"),
    ("output/filings.parquet", "Chapter 3 · Structure"),
    ("output/filers.csv", "Chapter 1 · Source"),
    ("submission/eda.py", "Chapter 2 · Interrogate"),
    ("agents/answer.py", "Chapter 4 · Serve"),
    ("submission/SUBMISSION.md", "required"),
    ("submission/AI_USAGE.md", "required"),
    ("submission/DEPENDENCIES.md", "required"),
    ("submission/ASSUMPTIONS.md", "required"),
]

# Not gated: producing this needs a live LLM endpoint, and not every candidate will have
# one reachable when they run this check. We still want it flagged if it's missing, so
# we warn rather than fail.
EXPECTED_NOT_REQUIRED = [
    ("output/agent_usage.json", "Chapter 4 · Serve"),
]

MEDIASPACE_RE = re.compile(r"mediaspace\.illinois\.edu", re.I)

fails: list[str] = []
warns: list[str] = []


def ok(msg: str) -> None:
    print(f"  {GREEN}PASS{RESET} {msg}")


def fail(msg: str, hint: str = "") -> None:
    fails.append(msg)
    print(f"  {RED}FAIL{RESET} {msg}")
    if hint:
        print(f"       {DIM}{hint}{RESET}")


def warn(msg: str, hint: str = "") -> None:
    warns.append(msg)
    print(f"  {YELLOW}WARN{RESET} {msg}")
    if hint:
        print(f"       {DIM}{hint}{RESET}")


def git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def check_git() -> str | None:
    """Confirm this is a repo with a remote and no unpushed work."""
    if git("rev-parse", "--git-dir") is None:
        fail("this is a git repository", "run from your repo root")
        return None
    ok("git repository")

    remote = git("remote", "get-url", "origin")
    if not remote:
        fail("origin remote is set",
             "create your repo from the template, then push to it")
        return None
    if "github.com" not in remote.lower():
        fail("origin points at GitHub", f"found: {remote}")
        return None
    ok(f"remote · {remote}")

    if git("status", "--porcelain"):
        warn("working tree is clean",
             "you have uncommitted changes; commit and push them")

    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
    local = git("rev-parse", branch)
    upstream = git("rev-parse", f"origin/{branch}")
    if upstream is None:
        fail(f"branch {branch!r} is pushed",
             f"git push -u origin {branch}")
    elif local != upstream:
        ahead = git("rev-list", "--count", f"origin/{branch}..{branch}") or "?"
        fail(f"local and origin/{branch} match",
             f"{ahead} commit(s) not pushed. We only see what is on GitHub.")
    else:
        ok(f"branch {branch!r} is pushed")

    count = git("rev-list", "--count", "HEAD")
    if count and int(count) < 3:
        warn(f"commit history ({count} commit(s))",
             "a single large commit at the deadline is a flag; commit as you work")
    elif count:
        ok(f"commit history · {count} commits")

    return remote


def check_files() -> None:
    root = Path(__file__).resolve().parent
    for rel, chapter in REQUIRED:
        p = root / rel
        if not p.exists():
            fail(f"{rel}", f"{chapter} — missing")
        elif p.stat().st_size == 0:
            fail(f"{rel}", f"{chapter} — file is empty")
        else:
            ok(f"{rel}  {DIM}{chapter}{RESET}")

    for rel, chapter in EXPECTED_NOT_REQUIRED:
        p = root / rel
        if not p.exists():
            warn(f"{rel}", f"{chapter} — missing; fine if you had no LLM endpoint to "
                            f"run against, otherwise commit it")
        elif p.stat().st_size == 0:
            warn(f"{rel}", f"{chapter} — file is empty")
        else:
            ok(f"{rel}  {DIM}{chapter}{RESET}")

    tracked = git("ls-files", "output/") or ""
    if "holdings.parquet" not in tracked:
        fail("output/ is committed to git",
             "your parquet exists on disk but is not tracked. Check whether a global "
             "gitignore excludes it:  git check-ignore -v output/holdings.parquet")
    else:
        ok("output/ is tracked by git")


def check_submission_md() -> None:
    p = Path(__file__).resolve().parent / "submission" / "SUBMISSION.md"
    if not p.exists():
        return
    text = p.read_text()

    # Anchored to end-of-line: an unfilled template leaves the label with nothing
    # after it, and a bare `##` on the next line must not count as an answer.
    def field(label: str) -> str | None:
        m = re.search(rf"\*\*{label}:\*\*[ \t]*([^\n#]+)", text)
        return m.group(1).strip() if m and m.group(1).strip() else None

    for label in ("Name", "NetID"):
        if field(label):
            ok(f"{label.lower()} filled in")
        else:
            fail(f"{label.lower()} filled in", "submission/SUBMISSION.md")

    raw = field("Link")
    link = re.match(r"(https?://\S+)", raw) if raw else None
    if not link:
        fail("video link filled in",
             "a submission without a video is incomplete and is not graded")
    elif not MEDIASPACE_RE.search(link.group(1)):
        warn("video is on Illinois MediaSpace",
             f"found {link.group(1)[:60]} — upload at "
             f"https://mediaspace.illinois.edu/upload/media, visibility Unlisted")
    else:
        ok("video link · MediaSpace")


def check_secrets() -> None:
    """Cheap scan for the mistake that is expensive to make."""
    root = Path(__file__).resolve().parent
    patterns = [
        (re.compile(r"sk-[A-Za-z0-9]{20,}"), "OpenAI-style key"),
        (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "GitHub token"),
        (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    ]
    hits: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in {".py", ".json", ".md", ".txt", ".yml", ".yaml"}:
            continue
        if any(part in {".git", ".cache", "__pycache__"} for part in p.parts):
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        for rx, label in patterns:
            if rx.search(text):
                hits.append(f"{p.relative_to(root)} ({label})")

    if (root / ".env").exists() and ".env" in (git("ls-files", ".env") or ""):
        hits.append(".env is committed")

    if hits:
        fail("no credentials committed", "; ".join(hits[:4]))
    else:
        ok("no credentials found")


def main() -> int:
    print(f"\n{'=' * 62}\n  Curator I · submission check\n{'=' * 62}\n")

    print("repository")
    remote = check_git()

    print("\nrequired files")
    check_files()

    print("\nsubmission form")
    check_submission_md()

    print("\nsecrets")
    check_secrets()

    print(f"\n{'-' * 62}")
    if fails:
        print(f"{RED}{len(fails)} problem(s) to fix before submitting{RESET}")
        for f in fails:
            print(f"  - {f}")
        return 1

    if warns:
        print(f"{YELLOW}{len(warns)} warning(s){RESET}")
        for w in warns:
            print(f"  - {w}")

    print(f"\n{GREEN}Local checks passed.{RESET}\n")
    print("Two things this script cannot verify from your machine:\n")
    print(f"  1. Your repo is {YELLOW}Private{RESET}")
    print(f"     Settings → General → Danger Zone\n")
    print(f"  2. {YELLOW}{BOT}{RESET} is a collaborator with Read access")
    print(f"     Settings → Collaborators → Add people\n")
    print(f"{DIM}Without the collaborator we cannot read your repo, and the")
    print(f"submission does not exist. Check it before you submit the form.{RESET}\n")
    if remote:
        owner_repo = re.search(r"github\.com[:/]+([^/]+/[^/.]+)", remote)
        if owner_repo:
            print(f"  Collaborators: https://github.com/{owner_repo.group(1)}"
                  f"/settings/access\n")
    print(f"Deadline: {DEADLINE}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
