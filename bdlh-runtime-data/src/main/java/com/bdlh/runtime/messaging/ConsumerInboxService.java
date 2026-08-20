package com.bdlh.runtime.messaging;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.UUID;

/** Local Java consumer deduplication.  Memory Service will use memory.consumer_inbox, never this table. */
@Service
public class ConsumerInboxService {

    private final JdbcTemplate jdbcTemplate;

    public ConsumerInboxService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    /**
     * Executes the supplied Java-side business mutation in the same transaction as the Inbox record.
     * A duplicate event returns false and never invokes the action.
     */
    @Transactional
    public boolean processOnce(String consumerGroup, UUID eventId, InboxAction action, String resultSummary) {
        if (consumerGroup == null || consumerGroup.trim().isEmpty() || eventId == null || action == null) {
            throw new IllegalArgumentException("consumer_group, event_id and action are required");
        }
        int inserted = jdbcTemplate.update(
                "INSERT INTO runtime.consumer_inbox(consumer_group, event_id, status) VALUES (?, ?, 'PROCESSING') "
                        + "ON CONFLICT (consumer_group, event_id) DO NOTHING",
                consumerGroup.trim(), eventId);
        if (inserted == 0) {
            return false;
        }
        action.run();
        jdbcTemplate.update(
                "UPDATE runtime.consumer_inbox SET status = 'PROCESSED', result_summary = ?, "
                        + "processed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
                        + "WHERE consumer_group = ? AND event_id = ?",
                summarize(resultSummary), consumerGroup.trim(), eventId);
        return true;
    }

    private static String summarize(String value) {
        if (value == null) {
            return null;
        }
        return value.substring(0, Math.min(value.length(), 1000));
    }

    @FunctionalInterface
    public interface InboxAction {
        void run();
    }
}
