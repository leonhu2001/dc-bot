DELETE FROM worker_payouts WHERE order_id = 32;
DELETE FROM customer_service_payouts WHERE order_id = 32;
DELETE FROM order_assignments WHERE order_id = 32;
DELETE FROM sync_events WHERE order_id = 32;
DELETE FROM web_orders WHERE id = 32;

SELECT id, status, category, item
FROM web_orders
WHERE id = 32;
