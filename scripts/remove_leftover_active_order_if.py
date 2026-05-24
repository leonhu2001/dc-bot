from pathlib import Path

path = Path("web/app/services/order_service.py")
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

out = []
i = 0
removed = False

while i < len(lines):
    line = lines[i]

    if "if active_order_count > 0:" in line:
        if_indent = len(line) - len(line.lstrip(" "))
        i += 1

        while i < len(lines):
            current = lines[i]
            stripped = current.strip()
            current_indent = len(current) - len(current.lstrip(" "))

            if stripped and current_indent <= if_indent:
                break

            i += 1

        removed = True
        continue

    out.append(line)
    i += 1

path.write_text("".join(out), encoding="utf-8")
print("removed leftover active_order_count if block" if removed else "no leftover block found")
