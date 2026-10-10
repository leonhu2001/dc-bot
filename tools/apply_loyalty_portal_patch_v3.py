from pathlib import Path

source_path = Path(__file__).with_name("apply_loyalty_portal_patch_v2.py")
source = source_path.read_text(encoding="utf-8")

# The current website checkout keeps use_wallet on one line (`use_wallet: false`).
# v2 targeted an older split-line spelling in both preview and formal payloads.
source = source.replace(
    '            use_wallet:\\n\'\'\'',
    '            use_wallet: false,\\n\'\'\'',
)

namespace = {
    "__name__": "__main__",
    "__file__": str(source_path),
    "__package__": None,
}
exec(compile(source, str(source_path), "exec"), namespace, namespace)
