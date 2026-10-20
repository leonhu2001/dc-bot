from __future__ import annotations


_INSTALLED = False
_CATEGORY_ORDER = {
    "delta_desktop_basic": 0,
    "delta_mobile_basic": 1,
    "valorant": 2,
    "lol": 3,
    "apex": 4,
    "steam": 5,
}


def install_vip_timer_runtime_order_v5() -> None:
    """Keep the in-ticket switch selector in the same game order as checkout."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer_runtime as runtime

    original_init = runtime.VipTimerCategorySelect.__init__

    def ordered_init(self, order_id: int) -> None:
        original_init(self, order_id)
        options = list(getattr(self, "options", ()) or ())
        options.sort(
            key=lambda option: (
                _CATEGORY_ORDER.get(str(getattr(option, "value", "") or ""), 99),
                str(getattr(option, "label", "") or ""),
            )
        )
        self.options = options

    runtime.VipTimerCategorySelect.__init__ = ordered_init
    _INSTALLED = True


__all__ = ["install_vip_timer_runtime_order_v5"]
