SELECT id, status, bot_order_no, ticket_channel_id, dispatch_message_id, category, item, amount, created_at, updated_at
FROM web_orders
ORDER BY id DESC
LIMIT 10;
