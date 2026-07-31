package com.stockwise.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.List;

/**
 * 会话状态的 Redis 存取服务。
 * 状态以 JSON 序列化保存，TTL 30 分钟；超时未续作即视为会话结束，自动清理。
 */
@Service
public class SessionStateService {

    private static final Duration TTL = Duration.ofMinutes(30);
    private static final DefaultRedisScript<Long> SAVE_SCRIPT = new DefaultRedisScript<>("""
            local current = redis.call('GET', KEYS[1])
            local expected = tonumber(ARGV[1])
            if not current then
                if expected ~= 0 then
                    return -1
                end
            else
                local ok, state = pcall(cjson.decode, current)
                if not ok then
                    return -2
                end
                local currentVersion = tonumber(state.version or 0)
                if currentVersion ~= expected then
                    return 0
                end
            end
            redis.call('PSETEX', KEYS[1], ARGV[3], ARGV[2])
            return expected + 1
            """, Long.class);
    private static final DefaultRedisScript<Long> CLEAR_SCRIPT = new DefaultRedisScript<>("""
            local current = redis.call('GET', KEYS[1])
            if not current then
                return 1
            end
            local ok, state = pcall(cjson.decode, current)
            if not ok then
                return -2
            end
            if tonumber(state.version or 0) ~= tonumber(ARGV[1]) then
                return 0
            end
            redis.call('DEL', KEYS[1])
            return 1
            """, Long.class);

    private final StringRedisTemplate redis;
    private final ObjectMapper mapper;

    public SessionStateService(StringRedisTemplate redis, ObjectMapper mapper) {
        this.redis = redis;
        this.mapper = mapper;
    }

    /**
     * 按状态当前版本执行 CAS 保存，成功后同步递增内存对象版本并刷新 TTL。
     */
    public long save(SessionState state) {
        long expectedVersion = state.getVersion();
        long nextVersion = expectedVersion + 1;
        state.setVersion(nextVersion);
        try {
            // 1. Lua 在 Redis 内原子比较版本并写入，禁止并发请求丢失更新
            Long result = redis.execute(
                    SAVE_SCRIPT,
                    List.of(key(state.getSessionId())),
                    String.valueOf(expectedVersion),
                    mapper.writeValueAsString(state),
                    String.valueOf(TTL.toMillis()));
            if (result == null || result <= 0) {
                state.setVersion(expectedVersion);
                throw new SessionStateConflictException(
                        "会话状态已被其他请求更新，请重新加载后再试，sessionId=" + state.getSessionId());
            }
            return result;
        } catch (SessionStateConflictException e) {
            throw e;
        } catch (Exception e) {
            state.setVersion(expectedVersion);
            throw new RuntimeException("保存会话状态失败", e);
        }
    }

    /**
     * 读取会话状态；不存在或反序列化失败返回 null，调用方按新会话处理。
     */
    public SessionState load(String sessionId) {
        // 1. 取 JSON 原文
        String json = redis.opsForValue().get(key(sessionId));
        if (json == null) {
            return null;
        }
        try {
            // 2. 反序列化为状态对象
            return mapper.readValue(json, SessionState.class);
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * 按最后读取版本清除会话状态，避免旧请求删除新请求已经推进的工作记忆。
     */
    public void clear(SessionState state) {
        Long result = redis.execute(
                CLEAR_SCRIPT,
                List.of(key(state.getSessionId())),
                String.valueOf(state.getVersion()));
        if (result == null || result <= 0) {
            throw new SessionStateConflictException(
                    "会话状态已被其他请求更新，拒绝清除，sessionId=" + state.getSessionId());
        }
    }

    private String key(String sessionId) {
        return "session:" + sessionId + ":state";
    }
}
