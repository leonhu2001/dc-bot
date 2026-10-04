import json
from types import SimpleNamespace

import pytest

from tools import diff_order_rules_baseline
from tools import run_health_checks


def test_report_step_does_not_raise_on_nonzero(monkeypatch, capsys):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(run_health_checks.subprocess, "run", fake_run)

    code = run_health_checks.run_report_step(
        "ORDER_RULES_BASELINE_DIFF",
        ["python", "diff.py"],
    )

    assert code == 1
    assert calls[0][1]["check"] is False
    assert "REPORT_ONLY_NONZERO" in capsys.readouterr().out


def test_baseline_diff_fails_on_added_rule_only(tmp_path, monkeypatch):
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "rules": {
                    "existing": {
                        "category": "general",
                        "label": "Existing",
                        "price_type": "fixed",
                        "price": 100,
                        "unit_label": "單",
                        "min_quantity": 1,
                        "max_quantity": 1,
                        "allowed_roles": ["top_protector"],
                        "allowed_role_ids": ["1"],
                        "required_staff_count": "1",
                        "resolved_required_staff_count_at_player_1": 1,
                        "min_protector_count": 0,
                        "allow_specify": False,
                        "max_specified_count": None,
                        "point_benefits_allowed": True,
                        "price_at_min_quantity": {"total_amount": 100},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        diff_order_rules_baseline,
        "BASELINE_PATH",
        baseline_path,
    )
    monkeypatch.setattr(
        diff_order_rules_baseline,
        "load_current_snapshot",
        lambda: {
            "rules": {
                "existing": json.loads(
                    baseline_path.read_text(encoding="utf-8")
                )["rules"]["existing"],
                "new_rule": {},
            }
        },
    )

    with pytest.raises(SystemExit) as exc:
        diff_order_rules_baseline.main()

    assert exc.value.code == 1
