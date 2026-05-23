from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYOUT_PATH = ROOT / "web" / "app" / "templates" / "layout.html"


def main() -> None:
    if not LAYOUT_PATH.exists():
        raise FileNotFoundError(f"找不到 {LAYOUT_PATH}")

    text = LAYOUT_PATH.read_text(encoding="utf-8")
    old = text

    replacements = {
        'href="/admin/payouts"': 'href="/admin/payouts/grouped"',
        "href='/admin/payouts'": "href='/admin/payouts/grouped'",
    }

    for src, dst in replacements.items():
        text = text.replace(src, dst)

    LAYOUT_PATH.write_text(text, encoding="utf-8")
    print("patched layout payout nav=", text != old)


if __name__ == "__main__":
    main()
