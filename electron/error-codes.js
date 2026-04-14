const ErrorCodes = {
  E_ENV_MISSING: "E_ENV_MISSING",
  E_ENV_PARSE_INVALID: "E_ENV_PARSE_INVALID",
  E_API_403_COINPAPRIKA: "E_API_403_COINPAPRIKA",
  E_API_RATE_LIMIT: "E_API_RATE_LIMIT",
  E_DB_CONNECT_FAIL: "E_DB_CONNECT_FAIL",
  E_SMTP_AUTH_FAIL: "E_SMTP_AUTH_FAIL",
  E_SCRIPT_EXIT_NONZERO: "E_SCRIPT_EXIT_NONZERO",
  E_RUNTIME_TIMEOUT: "E_RUNTIME_TIMEOUT",
  E_ARTIFACT_NOT_FOUND: "E_ARTIFACT_NOT_FOUND",
  E_JOB_ALREADY_RUNNING: "E_JOB_ALREADY_RUNNING",
  E_INTERPRETER_INVALID: "E_INTERPRETER_INVALID"
};

const ErrorHelp = {
  E_ENV_MISSING: "Thieu bien moi truong bat buoc.",
  E_ENV_PARSE_INVALID: "File .env sai dinh dang.",
  E_API_403_COINPAPRIKA: "CoinPaprika bi chan 403.",
  E_API_RATE_LIMIT: "Vuot gioi han request API.",
  E_DB_CONNECT_FAIL: "Khong ket noi duoc Aurora DB.",
  E_SMTP_AUTH_FAIL: "Dang nhap SMTP that bai.",
  E_SCRIPT_EXIT_NONZERO: "Script ket thuc voi exit code khac 0.",
  E_RUNTIME_TIMEOUT: "Tien trinh vuot timeout.",
  E_ARTIFACT_NOT_FOUND: "Khong tim thay artifact.",
  E_JOB_ALREADY_RUNNING: "Job cung loai dang chay.",
  E_INTERPRETER_INVALID: "Interpreter hien tai khong thuoc venv du an."
};

module.exports = { ErrorCodes, ErrorHelp };

