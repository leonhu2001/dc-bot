from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_order_rule_editor_exposes_direct_publish_action():
    script = (ROOT / "web/app/static/js/ui_tweaks.js").read_text(encoding="utf-8-sig")

    assert 'data.ruleDirectPublish = "1"' not in script
    assert 'publishButton.dataset.ruleDirectPublish = "1";' in script
    assert 'publishButton.textContent = "直接發布";' in script
    assert 'form[data-rule-edit-form]' in script
    assert 'form[data-form-kind="publish"]' in script


def test_direct_publish_reuses_preview_validation_before_publish():
    script = (ROOT / "web/app/static/js/ui_tweaks.js").read_text(encoding="utf-8-sig")

    preview_fetch = 'const previewResponse = await fetch(editForm.action'
    publish_fetch = 'const publishResponse = await fetch(publishAction'

    assert preview_fetch in script
    assert publish_fetch in script
    assert script.index(preview_fetch) < script.index(publish_fetch)
    assert 'new FormData(editForm)' in script
    assert 'new FormData(publishForm)' in script
    assert 'window.location.assign(publishResponse.url || window.location.href);' in script
