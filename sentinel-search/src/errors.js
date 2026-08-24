/**
 * 表示可安全返回给调用方的搜索服务错误。
 */
export class SearchWrapperError extends Error {
  constructor(status, code, message, details = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}
