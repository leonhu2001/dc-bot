# Order reporting workflow

Implementation branch for web order reporting, review, and post-close reminders.

- New reports apply only to orders closed after the feature cutoff.
- Any signed-in user may see the reporting navigation entry, but only assigned companions/workers may submit a report for an order.
- Workers only see orders they participated in and their own report history.
- Customer service/admin roles can review reports and see missing-report state in the operations/order views.
- A report records per-worker named status, whether the session was streamed, whether a recording is retained, optional recording holder, and free-form notes.
- Approval writes named-bonus state back to order assignments/payouts; submission itself does not change payout data.
