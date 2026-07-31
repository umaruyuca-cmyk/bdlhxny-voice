package com.stockwise.quota;

/**
 * 表示游客分析配额存储不可用，调用方必须失败关闭以保护付费链路。
 */
public class GuestAnalysisQuotaUnavailableException extends RuntimeException {

    public GuestAnalysisQuotaUnavailableException(String message, Throwable cause) {
        super(message, cause);
    }
}
