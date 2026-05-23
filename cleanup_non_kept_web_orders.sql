DELETE FROM worker_payouts WHERE order_id IN (
    SELECT id FROM web_orders WHERE status NOT IN ('active', 'stored', 'closed')
);

DELETE FROM customer_service_payouts WHERE order_id IN (
    SELECT id FROM web_orders WHERE status NOT IN ('active', 'stored', 'closed')
);

DELETE FROM order_assignments WHERE order_id IN (
    SELECT id FROM web_orders WHERE status NOT IN ('active', 'stored', 'closed')
);

DELETE FROM sync_events WHERE order_id IN (
    SELECT id FROM web_orders WHERE status NOT IN ('active', 'stored', 'closed')
);

DELETE FROM web_orders WHERE status NOT IN ('active', 'stored', 'closed');

SELECT status, COUNT(*) AS count
FROM web_orders
GROUP BY status;
