from __future__ import annotations

from web.app.services.order_groups import GROUP_SPECS, get_grouped_order_catalog


_FORBIDDEN_PUBLIC_DESCRIPTION_TERMS = (
    "身分組",
    "智慧派單",
    "派單只通知",
    "派單通知",
    "可接人員",
    "required_staff",
    "rule key",
)

_FILLER_DESCRIPTIONS = {
    "選擇適合你的方案",
    "選擇適合你的方案。",
    "絕巴技術陪服務",
    "絕巴技術陪服務。",
}


def test_builtin_public_group_descriptions_do_not_expose_internal_dispatch_terms():
    for spec in GROUP_SPECS:
        description = str(spec.get("description") or "").strip()
        lowered = description.lower()

        for term in _FORBIDDEN_PUBLIC_DESCRIPTION_TERMS:
            assert term.lower() not in lowered, (
                f"public group {spec.get('key')} exposes internal term {term!r}: "
                f"{description!r}"
            )

        assert description not in _FILLER_DESCRIPTIONS, (
            f"public group {spec.get('key')} still uses filler copy: {description!r}"
        )


def test_public_catalog_does_not_restore_generic_fallback_copy():
    groups = get_grouped_order_catalog("all")

    assert groups
    for group in groups:
        description = str(group.get("description") or "").strip()
        assert description not in _FILLER_DESCRIPTIONS
