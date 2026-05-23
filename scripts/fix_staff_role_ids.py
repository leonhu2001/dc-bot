from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / "web" / ".env"
ENV_EXAMPLE_PATH = PROJECT_ROOT / "web" / ".env.example"

REQUIRED = {
    "WORKER_ROLE_IDS": "1503701170504339458",
    "COMPANION_ROLE_IDS": "1503706721883783218",
}


def upsert_env(path: Path) -> bool:
    if not path.exists():
        return False

    text = path.read_text(encoding="utf-8")
    lines = []
    seen = set()

    for line in text.splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in REQUIRED:
            lines.append(f"{key}={REQUIRED[key]}")
            seen.add(key)
        else:
            lines.append(line)

    for key, value in REQUIRED.items():
        if key not in seen:
            lines.append(f"{key}={value}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def main() -> None:
    changed_env = upsert_env(ENV_PATH)
    changed_example = upsert_env(ENV_EXAMPLE_PATH)

    print(f"updated_env={changed_env} path={ENV_PATH}")
    print(f"updated_env_example={changed_example} path={ENV_EXAMPLE_PATH}")
    print("worker_role_ids=1503701170504339458")
    print("companion_role_ids=1503706721883783218")


if __name__ == "__main__":
    main()
