from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    login: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class MisCredentialsUpdate(BaseModel):
    mis_login: str = Field(..., min_length=1)
    mis_password: str = Field(..., min_length=1)


class MisConfigUpdate(BaseModel):
    base_url: str = Field(..., min_length=1)


class MisCredentialsStatus(BaseModel):
    """Состояние учётных данных ЕЦП. Пароль намеренно не отдаётся."""

    mis_login: str
    password_set: bool
    updated_at: str | None = None
