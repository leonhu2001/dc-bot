# Order reporting workflow

Implementation branch for web order reporting, review, and post-close reminders.

- Existing closed orders are backfilled as **approved / legacy** and display as `已報單`; nobody needs to retroactively fill them.
- After the reporting schema is initialized, only later transitions into `closed` create a new `未報單` record and worker reminder jobs.
- Any signed-in user may see the reporting navigation entry, but only assigned companions/workers may open or submit a report for an order.
- Workers only see closed orders they actually participated in and their own report history; changing the URL cannot expose another worker's order.
- One participant submits for the whole order. Teammates then see the shared pending/approved result instead of creating duplicate reports.
- Customer service/admin roles can review reports, correct fields, return reports with a required reason, see missing-report state in order history, and manually re-send reminders.
- A report records per-worker named status, whether the session was streamed, whether a recording is retained, optional recording holder, and free-form notes.
- Submission itself does not change payout data. Approval writes named-bonus state back to active order assignments and recalculates payouts while preserving already-paid payout state.
- The automatic Discord DM contains the direct `/dispatch/reports/{order_id}` URL. DM failure never blocks order closing or website reporting.
- The dispatch duty page remains open when customer service launches the back office; the back office link opens in a new tab.
