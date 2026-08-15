-- BDLH Agent Runtime: rename the Python-owned chat tables after the repository migration.
-- Existing installations may still contain the historical stockwise_* names.
-- The blocks are idempotent and leave a freshly initialized database untouched.

DO $$
BEGIN
    IF to_regclass('public.stockwise_chat_session') IS NOT NULL
       AND to_regclass('public.bdlh_runtime_chat_session') IS NULL THEN
        ALTER TABLE public.stockwise_chat_session RENAME TO bdlh_runtime_chat_session;
    END IF;

    IF to_regclass('public.stockwise_chat_message') IS NOT NULL
       AND to_regclass('public.bdlh_runtime_chat_message') IS NULL THEN
        ALTER TABLE public.stockwise_chat_message RENAME TO bdlh_runtime_chat_message;
    END IF;

    IF to_regclass('public.idx_stockwise_chat_message_session') IS NOT NULL
       AND to_regclass('public.idx_bdlh_runtime_chat_message_session') IS NULL THEN
        ALTER INDEX public.idx_stockwise_chat_message_session
            RENAME TO idx_bdlh_runtime_chat_message_session;
    END IF;
END
$$;
