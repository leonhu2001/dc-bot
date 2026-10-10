from __future__ import annotations

import tools.apply_loyalty_portal_patch as patch


_original_replace = patch.replace


def replace_v2(path: str, old: str, new: str, *, count: int = 1) -> None:
    legacy_keys = '    "valorant_entertain",\n    "valorant_tech",\n    "valorant_top_tech",\n'
    if path == "web/app/services/checkout_preview.py" and old == legacy_keys:
        text = patch.read(path)
        found = text.count(old)
        if found != 2:
            raise RuntimeError(f"{path}: expected 2 legacy Valorant exclusion blocks, found {found}")
        patch.write(path, text.replace(old, new))
        return
    _original_replace(path, old, new, count=count)


patch.replace = replace_v2


def patch_staff_profile_archive_v2() -> None:
    path = "views/staff_profiles.py"
    old = '''    channel = await _ensure_profile_thread_open_for_refresh(
        channel,
        staff_id=staff_id_text,
        reason=reason,
    )
    if channel is None:
        return False

    if not hasattr(channel, "fetch_message"):
        return False

    try:
        panel_message = await channel.fetch_message(message_id)
    except (
        discord.NotFound,
        discord.Forbidden,
        discord.HTTPException,
    ):
        return False

    latest_profile = get_staff_profile(staff_id_text)
    if latest_profile is None:
        return False

    try:
        await panel_message.edit(
            embed=build_staff_profile_embed(latest_profile),
            view=StaffProfilePanelView(staff_id_text),
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False,
            ),
        )
    except discord.HTTPException as exc:
        print(
            f"[staff-profile] refresh failed "
            f"staff_id={staff_id_text} "
            f"reason={reason}: {exc}"
        )
        return False

    print(
        f"[staff-profile] refreshed "
        f"staff_id={staff_id_text} "
        f"reason={reason}"
    )
    return True
'''
    new = '''    was_archived = bool(getattr(channel, "archived", False))
    channel = await _ensure_profile_thread_open_for_refresh(
        channel,
        staff_id=staff_id_text,
        reason=reason,
    )
    if channel is None:
        return False

    try:
        if not hasattr(channel, "fetch_message"):
            return False

        try:
            panel_message = await channel.fetch_message(message_id)
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            return False

        latest_profile = get_staff_profile(staff_id_text)
        if latest_profile is None:
            return False

        try:
            await panel_message.edit(
                embed=build_staff_profile_embed(latest_profile),
                view=StaffProfilePanelView(staff_id_text),
                allowed_mentions=discord.AllowedMentions(
                    users=False,
                    roles=False,
                    everyone=False,
                ),
            )
        except discord.HTTPException as exc:
            print(
                f"[staff-profile] refresh failed "
                f"staff_id={staff_id_text} "
                f"reason={reason}: {exc}"
            )
            return False

        print(
            f"[staff-profile] refreshed "
            f"staff_id={staff_id_text} "
            f"reason={reason}"
        )
        return True
    finally:
        # Background refresh may temporarily reopen an archived thread so the
        # saved panel can be edited. Put it back immediately; genuinely active
        # conversations are never auto-archived.
        if was_archived and not bool(getattr(channel, "archived", False)):
            edit_channel = getattr(channel, "edit", None)
            if callable(edit_channel):
                try:
                    restored = await edit_channel(
                        archived=True,
                        reason=f"Staff profile refresh complete: {reason}"[:512],
                    )
                    if restored is not None:
                        channel = restored
                except (
                    discord.NotFound,
                    discord.Forbidden,
                    discord.HTTPException,
                ) as exc:
                    print(
                        f"[staff-profile] rearchive thread failed "
                        f"staff_id={staff_id_text} reason={reason}: {exc}"
                    )
'''
    patch.replace(path, old, new)

    test_path = "tests/test_staff_profile_archived_thread_refresh.py"
    text = patch.read(test_path)
    text = text.replace(
        "test_archived_public_profile_thread_is_reopened_and_left_active",
        "test_archived_public_profile_thread_is_reopened_then_rearchived",
    )
    text = text.replace("assert thread.edit_calls == [False]", "assert thread.edit_calls == [False, True]")
    text = text.replace("assert thread.archived is False", "assert thread.archived is True", 1)
    patch.write(test_path, text)


patch.patch_staff_profile_archive = patch_staff_profile_archive_v2
patch.main()
