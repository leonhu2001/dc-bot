from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SOURCE = (ROOT / "services" / "acceptance" / "runtime.py").read_text(
    encoding="utf-8"
)
STORAGE_SOURCE = (ROOT / "services" / "order_storage_runtime.py").read_text(
    encoding="utf-8"
)


def test_active_resume_prefers_canonical_active_assignments():
    assert "_apply_acceptance_state_to_claim_data_base" in RUNTIME_SOURCE
    assert '!= "active"' in RUNTIME_SOURCE
    assert "OrderAssignment.order_id == int(order_id)" in RUNTIME_SOURCE
    assert "OrderAssignment.is_active.is_(True)" in RUNTIME_SOURCE
    assert 'role_type == "companion"' in RUNTIME_SOURCE
    assert 'claim_data["companion"] = companion_ids' in RUNTIME_SOURCE
    assert 'claim_data["booster"] = booster_ids' in RUNTIME_SOURCE


def test_resume_flow_still_applies_acceptance_state_before_rendering_receivers():
    resume_source = STORAGE_SOURCE.split("async def resume_stored_order(", 1)[1]
    apply_index = resume_source.index(
        "_apply_acceptance_state_to_claim_data(claim_data, acceptance_state)"
    )
    receiver_index = resume_source.index(
        'companion_ids = sorted(claim_data.get("companion", set()))'
    )
    assert apply_index < receiver_index
