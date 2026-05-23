DELETE FROM sync_events WHERE order_id = 34;

INSERT INTO sync_events (
    order_id,
    event_type,
    status,
    error_message,
    created_at
) VALUES (
    34,
    'order_claimed',
    'pending',
    NULL,
    datetime('now')
);

SELECT id, order_id, event_type, status, error_message, created_at
FROM sync_events
WHERE order_id = 34
ORDER BY id DESC;
