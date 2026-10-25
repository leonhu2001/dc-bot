from __future__ import annotations

from pathlib import Path


ROOT = Path(".")


def test_member_roulette_owns_stable_stylesheet_without_touching_draw_script() -> None:
    template = (ROOT / "web/app/templates/member_roulette.html").read_text(encoding="utf-8")
    stable = ROOT / "web/app/static/css/pages/member_roulette.css"
    legacy = ROOT / "web/app/static/css/pages/member_roulette_inline_1.css"

    assert '/static/css/pages/member_roulette.css?v=20261013' in template
    assert "member_roulette_inline_1.css" not in template
    assert stable.is_file()
    assert not legacy.exists()
    assert ".wheel-stage" in stable.read_text(encoding="utf-8")
    assert 'DRAW_URL="/me/orders/{{ order.id }}/roulette/draw"' in template
    assert "async function spin()" in template
