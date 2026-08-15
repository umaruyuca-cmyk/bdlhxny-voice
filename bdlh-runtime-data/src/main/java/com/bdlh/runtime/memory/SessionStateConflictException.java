package com.bdlh.runtime.memory;

/**
 * 表示 Redis 会话版本已被其他请求推进，当前请求不得覆盖较新的工作记忆。
 */
public class SessionStateConflictException extends RuntimeException {

    public SessionStateConflictException(String message) {
        super(message);
    }
}
