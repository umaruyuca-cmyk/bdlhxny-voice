/**
 * 表示可以安全映射为 HTTP 响应的 Wrapper 业务错误。
 */
export class WrapperError extends Error {
  constructor(status, code, message, details = null) {
    super(message);
    this.name = 'WrapperError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}
