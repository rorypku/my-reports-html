#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REPO = "rorypku/my-reports-requests"
DEFAULT_TITLE_PREFIX = "report request:"
DEFAULT_AGENT_DIR = "/Users/kai/agent/investment_research/sitrep-agent"
REQUEST_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._:+/\-]{0,79}")


def run(command: list[str], cwd: Path | None = None, capture: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except subprocess.CalledProcessError as error:
        if capture:
            if error.stdout:
                print(error.stdout, file=sys.stderr, end="")
            if error.stderr:
                print(error.stderr, file=sys.stderr, end="")
        raise


def issue_request(issue: dict[str, Any], title_prefix: str) -> str | None:
    title = str(issue["title"]).strip()
    body = str(issue.get("body") or "").strip()

    if title.lower().startswith(title_prefix.lower()):
        request = title[len(title_prefix):].strip()
        if request:
            return request

    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith("<!--"):
            return line

    return None


def validate_request(value: str) -> str:
    request = re.sub(r"\s+", " ", value.strip())
    if not REQUEST_PATTERN.fullmatch(request):
        raise ValueError(
            f"Invalid request {request!r}. Use 1-80 characters: letters, numbers, spaces, . _ : + / -"
        )
    return request


def parse_allowed_authors(values: list[str], environment_value: str | None) -> set[str]:
    authors = set(values)
    if environment_value:
        authors.update(author.strip() for author in environment_value.split(","))
    return {author for author in authors if author}


def load_open_issues(gh_bin: str, repo: str, limit: int) -> list[dict[str, Any]]:
    result = run(
        [
            gh_bin,
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,title,body,url,createdAt,author",
        ]
    )
    return json.loads(result.stdout)


def matching_requests(
    issues: list[dict[str, Any]],
    title_prefix: str,
    allowed_authors: set[str],
) -> list[tuple[dict[str, Any], str]]:
    matches: list[tuple[dict[str, Any], str]] = []
    for issue in issues:
        if not str(issue["title"]).strip().lower().startswith(title_prefix.lower()):
            continue
        author = str(issue.get("author", {}).get("login") or "")
        if allowed_authors and author not in allowed_authors:
            raise PermissionError(f"Issue #{issue['number']} was opened by unauthorized author {author!r}: {issue['url']}")
        request = issue_request(issue, title_prefix)
        if request is None:
            raise ValueError(f"Issue #{issue['number']} has no request text: {issue['url']}")
        matches.append((issue, validate_request(request)))
    return sorted(matches, key=lambda item: item[0]["createdAt"])


def comment_issue(gh_bin: str, repo: str, number: int, body: str) -> None:
    run([gh_bin, "issue", "comment", str(number), "--repo", repo, "--body", body])


def close_issue(gh_bin: str, repo: str, number: int) -> None:
    run([gh_bin, "issue", "close", str(number), "--repo", repo, "--reason", "completed"])


def process_request(
    *,
    gh_bin: str,
    codex_bin: str,
    repo: str,
    agent_dir: Path,
    issue: dict[str, Any],
    request: str,
    dry_run: bool,
) -> None:
    number = int(issue["number"])
    command = [codex_bin, "exec", "-C", str(agent_dir), request]

    if dry_run:
        author = str(issue.get("author", {}).get("login") or "unknown")
        print(f"dry-run: issue #{number} by {author}: {' '.join(command)}")
        return

    print(f"processing issue #{number}: {request}")
    try:
        run(command, capture=False)
    except subprocess.CalledProcessError as error:
        comment_issue(
            gh_bin,
            repo,
            number,
            "\n".join(
                [
                    "Local processing failed.",
                    "",
                    f"Request: `{request}`",
                    f"Command: `{' '.join(command)}`",
                    f"Exit code: `{error.returncode}`",
                ]
            ),
        )
        raise

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    comment_issue(
        gh_bin,
        repo,
        number,
        f"Processed locally at {timestamp} with `{' '.join(command)}`.",
    )
    close_issue(gh_bin, repo, number)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process GitHub Issues as local report requests.")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO))
    parser.add_argument("--agent-dir", type=Path, default=Path(os.environ.get("SITREP_AGENT_DIR", DEFAULT_AGENT_DIR)))
    parser.add_argument("--title-prefix", default=os.environ.get("REPORT_REQUEST_TITLE_PREFIX", DEFAULT_TITLE_PREFIX))
    parser.add_argument("--gh-bin", default=os.environ.get("GH_BIN", "gh"))
    parser.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-requests", type=int, default=1)
    parser.add_argument(
        "--allowed-author",
        action="append",
        default=[],
        help="GitHub login allowed to trigger local processing. May be repeated.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    lock_path = repo_root / ".report-request-watcher.lock"

    if args.max_requests < 1:
        raise ValueError("--max-requests must be at least 1")
    if not args.agent_dir.is_dir():
        raise FileNotFoundError(f"Agent directory does not exist: {args.agent_dir}")

    with lock_path.open("w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"another watcher is already running: {lock_path}", file=sys.stderr)
            return 75

        allowed_authors = parse_allowed_authors(args.allowed_author, os.environ.get("REPORT_REQUEST_ALLOWED_AUTHORS"))
        issues = load_open_issues(args.gh_bin, args.repo, args.limit)
        requests = matching_requests(issues, args.title_prefix, allowed_authors)
        if not requests:
            print("no open report requests")
            return 0

        for issue, request in requests[: args.max_requests]:
            process_request(
                gh_bin=args.gh_bin,
                codex_bin=args.codex_bin,
                repo=args.repo,
                agent_dir=args.agent_dir,
                issue=issue,
                request=request,
                dry_run=args.dry_run,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
