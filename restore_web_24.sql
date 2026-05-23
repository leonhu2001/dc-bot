UPDATE web_orders
SET status = 'active', updated_at = datetime('now')
WHERE id = 24;

SELECT id, status, ticket_channel_id, dispatch_message_id, category, item
FROM web_orders
WHERE id = 24;
