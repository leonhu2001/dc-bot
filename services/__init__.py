"""Shared services package.

Current storefront business values live in services.order_rules, while Discord catalog
presentation metadata lives in services.orders. Importing this package validates the
final rule registry but does not mutate prices, pricing modes, labels, or specify fees.
"""

from . import order_rules as _order_rules


_order_rules.validate_rules()
