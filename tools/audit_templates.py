from __future__ import annotations

import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError


ROOT = Path(os.environ.get("DC_BOT_ROOT", "/opt/dc-bot"))
TEMPLATES = ROOT / "web" / "app" / "templates"


def title(text: str) -> None:
    print("\n" + "=" * 100)
    print(text)
    print("=" * 100)


def main() -> None:
    title("TEMPLATE_AUDIT")

    if not TEMPLATES.exists():
        raise SystemExit(f"templates folder not found: {TEMPLATES}")

    env = Environment(loader=FileSystemLoader(str(TEMPLATES)))

    template_files = sorted(
        path
        for path in TEMPLATES.rglob("*")
        if path.suffix.lower() in {".html", ".jinja", ".jinja2"}
    )

    print("ROOT:", ROOT)
    print("TEMPLATES:", TEMPLATES)
    print("TEMPLATE_COUNT:", len(template_files))

    errors: list[str] = []

    for path in template_files:
        rel = path.relative_to(TEMPLATES).as_posix()

        try:
            env.get_template(rel)
            print("OK:", rel)
        except TemplateSyntaxError as exc:
            message = f"{rel}: line {exc.lineno}: {exc.message}"
            print("ERROR:", message)
            errors.append(message)
        except Exception as exc:
            message = f"{rel}: {type(exc).__name__}: {exc}"
            print("ERROR:", message)
            errors.append(message)

    title("ERRORS")

    if errors:
        for error in errors:
            print("ERROR:", error)

        raise SystemExit(1)

    print("NONE")

    title("REPORT_DONE")
    print("TEMPLATE_AUDIT_PASS")


if __name__ == "__main__":
    main()
