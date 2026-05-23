SELECT id, status, category, item FROM web_orders WHERE id = 31;
UPDATE web_orders SET status = 'closed', updated_at = datetime('now') WHERE id = 31;
SELECT changes();
SELECT id, status, category, item FROM web_orders WHERE id = 31;
