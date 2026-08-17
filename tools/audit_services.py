from __future__ import annotations

import subprocess
from dataclasses import dataclass


SERVICES = [
    "dc-bot.service",
    "dc-bot-dashboard.service",
]

ERROR_PATTERNS = [
    "Traceback",
    "SyntaxError",
    "IndentationError",
    "NameError",
    "OperationalError",
    "TemplateSyntaxError",
    "UndefinedError",
    "Exception",
    "failed",
    "失敗",
]


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def title(text: str) -> None:
    print("\n" + "=" * 100)
    print(text)
    print("=" * 100)


def run(command: list[str]) -> CommandResult:
    proc = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    return CommandResult(proc.returncode, proc.stdout.strip(), proc.stderr.strip())


def main() -> None:
    title("SERVICE_AUDIT")

    errors: list[str] = []

    for service in SERVICES:
        title(f"SERVICE_STATUS {service}")

        active = run(["systemctl", "is-active", service])
        enabled = run(["systemctl", "is-enabled", service])

        print("is-active:", active.stdout or active.stderr or f"returncode={active.returncode}")
        print("is-enabled:", enabled.stdout or enabled.stderr or f"returncode={enabled.returncode}")

        if active.stdout.strip() != "active":
            errors.append(f"{service}: not active")

        status = run(["systemctl", "status", service, "--no-pager"])
        print("\nSTATUS_HEAD")
        for line in (status.stdout or status.stderr).splitlines()[:18]:
            print(line)

    title("RECENT_JOURNAL_ERRORS")

    for service in SERVICES:
        journal = run([
            "journalctl",
            "-u",
            service,
            "--since",
            "10 minutes ago",
            "--no-pager",
        ])

        matched_lines = []

        for line in (journal.stdout + "\n" + journal.stderr).splitlines():
            lower_line = line.lower()

            if any(pattern.lower() in lower_line for pattern in ERROR_PATTERNS):
                matched_lines.append(line)

        print("\n" + "-" * 80)
        print(service)

        if matched_lines:
            for line in matched_lines[-80:]:
                print(line)

            errors.append(f"{service}: recent journal error lines found")
        else:
            print("NONE")

    title("ERRORS")

    if errors:
        for error in errors:
            print("ERROR:", error)

        raise SystemExit(1)

    print("NONE")

    title("REPORT_DONE")
    print("SERVICE_AUDIT_PASS")


if __name__ == "__main__":
    main()
