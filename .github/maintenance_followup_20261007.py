from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_base_maintenance():
    path = ROOT / ".github" / "maintenance_20261007.py"
    spec = importlib.util.spec_from_file_location("maintenance_20261007", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load base maintenance script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repair_remaining_text_corruption() -> None:
    acceptance = ROOT / "services" / "acceptance" / "runtime.py"
    text = acceptance.read_text(encoding="utf-8")
    old = "# runtime.py ?? services/acceptance/?\n    # web_dashboard.db ????????"
    new = "# runtime.py 位於 services/acceptance/；web_dashboard.db 位於專案根目錄。"
    count = text.count(old)
    if count != 4:
        raise RuntimeError(f"expected 4 corrupted acceptance comments, found {count}")
    acceptance.write_text(text.replace(old, new), encoding="utf-8")

    home = ROOT / "web" / "app" / "templates" / "home.html"
    text = home.read_text(encoding="utf-8")
    if 'aria-label="???????"' not in text or 'alt="?????????"' not in text:
        raise RuntimeError("home hero corrupted accessibility copy target not found")
    text = text.replace('aria-label="???????"', 'aria-label="魔丸娛樂吉祥物主視覺"', 1)
    text = text.replace('alt="?????????"', 'alt="魔丸娛樂吉祥物"', 1)
    home.write_text(text, encoding="utf-8")


def source_text_sanity_check() -> None:
    bad: list[str] = []
    roots = [
        ROOT / "bot.py",
        ROOT / "cogs",
        ROOT / "core",
        ROOT / "services",
        ROOT / "shared",
        ROOT / "views",
        ROOT / "web" / "app",
    ]
    for root in roots:
        paths = [root] if root.is_file() else list(root.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix.lower() not in {".py", ".html", ".js", ".yml", ".yaml"}:
                continue
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            if "�" in text:
                bad.append(f"replacement character: {path.relative_to(ROOT)}")

            # SQLite GLOB uses ? as a one-character wildcard. YYYY-MM is
            # intentionally matched as GLOB '????-??' in payout queries.
            checked = text.replace("GLOB '????-??'", "")
            if "???" in checked and "tests" not in path.parts:
                bad.append(f"suspicious ???: {path.relative_to(ROOT)}")

    if bad:
        raise RuntimeError("source text sanity failed: " + "; ".join(bad))


def main() -> None:
    base = load_base_maintenance()
    base.repair_vip_benefit_display()
    base.repair_smart_dispatch_cadence()
    base.strengthen_compile_coverage()
    base.update_regressions()
    repair_remaining_text_corruption()
    source_text_sanity_check()


if __name__ == "__main__":
    main()
