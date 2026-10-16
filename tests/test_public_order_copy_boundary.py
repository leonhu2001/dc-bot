from web.app.services.order_groups import GROUP_SPECS


INTERNAL_PUBLIC_COPY_TERMS = (
    "身分組",
    "智慧派單",
    "派單只通知",
    "派單通知",
    "可接人員",
    "required_staff",
    "rule key",
)


def test_public_group_descriptions_do_not_expose_internal_dispatch_rules():
    descriptions = [
        str(spec.get("description") or "")
        for spec in GROUP_SPECS
    ]

    leaked = {
        term: [description for description in descriptions if term.lower() in description.lower()]
        for term in INTERNAL_PUBLIC_COPY_TERMS
    }
    leaked = {term: matches for term, matches in leaked.items() if matches}

    assert leaked == {}


def test_entertainment_public_copy_keeps_customer_benefit_without_role_requirements():
    by_key = {str(spec.get("key")): spec for spec in GROUP_SPECS}

    desktop = str(by_key["entertain"].get("description") or "")
    mobile = str(by_key["entertain_mobile"].get("description") or "")

    assert "娛樂陪福利累積" in desktop
    assert "娛樂陪福利累積" in mobile
    assert "身分組" not in desktop
    assert "身分組" not in mobile
