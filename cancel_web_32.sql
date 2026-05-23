UPDATE web_orders
SET status = 'cancelled', updated_at = datetime('now')
WHERE id = 32;

SELECT id, status, category, item
FROM web_orders
WHERE id = 32;
