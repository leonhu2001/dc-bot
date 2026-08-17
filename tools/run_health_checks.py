from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(os.environ.get("DC_BOT_ROOT", "/opt/dc-bot"))
PYTHONPATH = str(ROOT)


def title(text: str) -> None:
    print("\n" + "=" * 100)
    print(text)
    print("=" * 100)


def run_step(name: str, command: list[str]) -> None:
    title(name)
    print("COMMAND:", " ".join(command))

    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH

    subprocess.run(
        command,
        cwd=str(ROOT),
        env=env,
        check=True,
    )


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f"ROOT not found: {ROOT}")

    python_bin = Path(sys.executable)

    title("DC_BOT_HEALTH_CHECK")
    print("ROOT:", ROOT)
    print("PYTHON:", python_bin)

    compile_targets = [
        ROOT / "bot.py",
        ROOT / "shared" / "models.py",
        ROOT / "shared" / "order_acceptance.py",
        ROOT / "services" / "order_rules.py",
        ROOT / "tools" / "audit_order_integrity.py",
        ROOT / "tools" / "audit_order_rules.py",
    ]

    for target in compile_targets:
        if target.exists():
            run_step(
                f"PY_COMPILE {target.relative_to(ROOT)}",
                [str(python_bin), "-m", "py_compile", str(target)],
            )
        else:
            raise SystemExit(f"missing required file: {target}")

    run_step(
        "ORDER_RULES_AUDIT",
        [str(python_bin), str(ROOT / "tools" / "audit_order_rules.py")],
    )

    run_step(
        "ORDER_INTEGRITY_AUDIT",
        [str(python_bin), str(ROOT / "tools" / "audit_order_integrity.py")],
    )

    title("HEALTH_CHECK_DONE")
    print("DC_BOT_HEALTH_CHECK_PASS")


if __name__ == "__main__":
    main()
