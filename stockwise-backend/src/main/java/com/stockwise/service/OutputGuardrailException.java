package com.stockwise.service;

/**
 * 表示模型输出在发送给客户端之前被合规护栏阻断。
 */
public class OutputGuardrailException extends RuntimeException {

    public OutputGuardrailException(String message) {
        super(message);
    }
}
