from pathlib import Path
import runpy

helper = Path("tools/tmp_patch_benefit_bulk_issue.py")
text = helper.read_text(encoding="utf-8")
needle = '    if count != 1:\n        raise RuntimeError(f"{path}: expected exactly one match, found {count}")\n'
replacement = '    if count < 1:\n        raise RuntimeError(f"{path}: expected at least one match, found {count}")\n'
if text.count(needle) != 1:
    raise RuntimeError("temporary helper guard did not match")
helper.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
runpy.run_path(str(helper), run_name="__main__")
