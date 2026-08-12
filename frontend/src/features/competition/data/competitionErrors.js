export class PreviewReadOnlyError extends Error {
  constructor(action) {
    super(`预览环境不会执行${action}`);
    this.name = 'PreviewReadOnlyError';
    this.code = 'preview-read-only';
  }
}

export class CompetitionRequestError extends Error {
  constructor(message, status, code = 'request-failed') {
    super(message);
    this.name = 'CompetitionRequestError';
    this.status = status;
    this.code = status === 403 ? 'forbidden' : code;
  }
}
