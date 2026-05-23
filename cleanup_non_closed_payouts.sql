DELETE FROM worker_payouts
WHERE order_id IN (
    SELECT id FROM web_orders
    WHERE status <> 'closed'
);

DELETE FROM customer_service_payouts
WHERE order_id IN (
    SELECT id FROM web_orders
    WHERE status <> 'closed'
);

SELECT w.status, COUNT(p.id) AS payout_rows, COALESCE(SUM(p.final_payout), 0) AS worker_total
FROM web_orders w
LEFT JOIN worker_payouts p ON p.order_id = w.id
GROUP BY w.status
ORDER BY w.status;
