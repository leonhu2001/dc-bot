UPDATE worker_payouts
SET gross_share = 0,
    base_payout = 0,
    named_bonus_amount = 0,
    final_payout = 0
WHERE order_id IN (
    SELECT id FROM web_orders
    WHERE status <> 'closed'
);

SELECT w.status, COUNT(p.id) AS rows, COALESCE(SUM(p.final_payout), 0) AS total
FROM web_orders w
LEFT JOIN worker_payouts p ON p.order_id = w.id
GROUP BY w.status
ORDER BY w.status;
