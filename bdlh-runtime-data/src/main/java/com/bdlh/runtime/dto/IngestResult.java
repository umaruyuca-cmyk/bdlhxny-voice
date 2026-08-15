package com.bdlh.runtime.dto;

/**
 * 单条候选知识的入库结果。
 *
 * @param status 入库状态：ingested / duplicate / low_confidence / error
 * @param reason 附加说明，供日志与前端展示
 */
public record IngestResult(String status, String reason) {
}
