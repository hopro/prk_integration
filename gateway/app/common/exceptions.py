from starlette import status


class AppException(Exception):
    def __init__(self, code: str, message: str, http_status: int = status.HTTP_400_BAD_REQUEST):
        self.code = code
        self.message = message
        self.http_status = http_status


class MisHtmlError(AppException):
    def __init__(self, message: str = "External MIS returned HTML page"):
        super().__init__(
            code="MIS_HTML_ERROR",
            message=message,
            http_status=status.HTTP_502_BAD_GATEWAY,
        )


class MisAuthError(AppException):
    def __init__(self, message: str = "MIS authentication failed"):
        super().__init__(
            code="MIS_AUTH_FAILED",
            message=message,
            http_status=status.HTTP_502_BAD_GATEWAY,
        )


class CredentialsError(AppException):
    def __init__(self, message: str = "Invalid credentials"):
        super().__init__(
            code="INVALID_CREDENTIALS",
            message=message,
            http_status=status.HTTP_401_UNAUTHORIZED,
        )


class TokenExpiredError(AppException):
    def __init__(self):
        super().__init__(
            code="TOKEN_EXPIRED",
            message="Token has expired",
            http_status=status.HTTP_401_UNAUTHORIZED,
        )


class TokenInvalidError(AppException):
    def __init__(self, message: str = "Invalid token"):
        super().__init__(
            code="TOKEN_INVALID",
            message=message,
            http_status=status.HTTP_401_UNAUTHORIZED,
        )


class SessionNotFoundError(AppException):
    def __init__(self):
        super().__init__(
            code="SESSION_NOT_FOUND",
            message="MIS session not found. Please re-authenticate.",
            http_status=status.HTTP_401_UNAUTHORIZED,
        )
