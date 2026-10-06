import asyncio
import logging
import re

import httpx
from redis.asyncio import Redis

from app.config import get_settings
from app.common.exceptions import MisHtmlError, MisAuthError
from app.mis.session import MisSession, delete_mis_session

logger = logging.getLogger(__name__)
settings = get_settings()

LOGIN_PATH = "/api/user/login"
LOGOUT_PATH = "/api/user/logout"
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"

# Маркеры страницы входа ЕЦП. Нужны только для понятных сообщений об ошибке:
# сам факт HTML-ответа уже означает, что сессия мертва.
_LOGIN_PAGE_MARKERS = (
    "method=Logon",
    "name=\"psw\"",
    "api/user/login",
    "checkPOSTcardauth",
)


def _try_json(response: httpx.Response) -> dict | None:
    try:
        return response.json()
    except Exception:
        return None


def _is_html_content(response: httpx.Response) -> bool:
    ct = response.headers.get("content-type", "")
    if "text/html" in ct:
        return True
    text = response.text.strip()
    if text.startswith(("{", "[")):
        return False
    return text.startswith(("<", "<!DOCTYPE", "<html"))


def _parse_cookies(response: httpx.Response) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for header in response.headers.get_list("set-cookie"):
        parts = header.split(";")[0]
        if "=" in parts:
            name, value = parts.split("=", 1)
            cookies[name.strip()] = value.strip()
    return cookies


def _extract_error_from_html(html: str) -> str | None:
    match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r'class="[^"]*error[^"]*"[^>]*>(.*?)<', html, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def _describe_html(html: str) -> str:
    """Понятное описание HTML-ответа ЕЦП вместо безликой константы."""
    title = _extract_error_from_html(html)
    login_page = any(marker in html for marker in _LOGIN_PAGE_MARKERS)
    if login_page:
        return f"ЕЦП вернула страницу входа вместо данных (сессия истекла{': ' + title if title else ''})"
    if title:
        return f"ЕЦП вернула HTML-страницу вместо данных (заголовок: «{title}»)"
    return "ЕЦП вернула HTML вместо данных (сессия истекла)"


class MisClient:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        # Базовый адрес ЕЦП меняется на лету через PUT /api/v1/mis-config,
        # поэтому хранится здесь, а не в неизменяемой константе.
        self._base_url: str | None = None
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return self._base_url or settings.mis_base_url

    def set_base_url(self, url: str) -> None:
        url = (url or "").strip().rstrip("/")
        if url and url != self.base_url:
            logger.info("MIS base URL changed: %s -> %s", self.base_url, url)
            self._base_url = url
            # Клиент привязан к прежнему хосту — следующий запрос создаст новый.
            if self._client and not self._client.is_closed:
                self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=settings.mis_request_timeout,
                follow_redirects=True,
            )
        return self._client

    def _headers(self, form: bool = False) -> dict[str, str]:
        base = self.base_url
        headers = {
            "User-Agent": BROWSER_UA,
            "Accept": "*/*",
            "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": base,
            "Referer": f"{base}/?c=promed",
            "Connection": "keep-alive",
        }
        if form:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        return headers

    async def authenticate(self, login: str, password: str) -> MisSession:
        client = await self._get_client()
        response = await client.get(
            LOGIN_PATH,
            params={"Login": login, "Password": password},
            headers=self._headers(),
        )
        logger.info(
            "MIS auth %s: status=%s ct=%s", login, response.status_code,
            response.headers.get("content-type"),
        )

        data = _try_json(response)
        if data is None:
            if _is_html_content(response):
                logger.warning("MIS auth returned HTML for %s", login)
                raise MisAuthError(_describe_html(response.text))
            logger.error("MIS auth non-JSON response: %.300s", response.text)
            raise MisAuthError("Некорректный ответ ЕЦП при авторизации")

        if not isinstance(data, dict):
            raise MisAuthError("Неожиданный формат ответа ЕЦП при авторизации")

        logger.info("MIS auth response: %s", data)

        if data.get("error_code"):
            message = (
                data.get("error_msg") or data.get("message") or data.get("error")
                or f"error_code={data.get('error_code')}"
            )
            raise MisAuthError(f"ЕЦП отклонила логин/пароль ({message})")

        sess_id = data.get("sess_id") or data.get("Sess_id") or data.get("session_id")
        if sess_id is None:
            response_login = data.get("Login") or data.get("login")
            if response_login:
                sess_id = response_login
            else:
                message = (
                    data.get("error_msg") or data.get("message")
                    or data.get("error") or str(data)
                )
                raise MisAuthError(f"Авторизация в ЕЦП не удалась: {message}")

        cookies = _parse_cookies(response)
        csrf_token = cookies.get("csrfToken")
        # ЕЦП не выдаёт login через Set-Cookie, но принимает его в куках.
        cookies.setdefault("login", login)

        expires = (data.get("data") or {}).get("password_expiration_date")
        logger.info(
            "MIS auth OK for %s (sess_id=%s, cookies=%s%s)",
            login,
            sess_id,
            sorted(cookies),
            f", пароль ЕЦП истекает {expires}" if expires else "",
        )

        return MisSession(
            sess_id=str(sess_id),
            cookies=cookies,
            csrf_token=csrf_token,
        )

    async def request(
        self,
        method: str,
        path: str,
        session: MisSession,
        data: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        client = await self._get_client()
        cookies = dict(session.cookies)
        cookies["sess_id"] = session.sess_id
        if session.csrf_token:
            cookies["csrfToken"] = session.csrf_token

        response = await client.request(
            method=method,
            url=path,
            params=params,
            data=data,
            cookies=cookies,
            headers=self._headers(form=bool(data)),
        )

        logger.info(
            "MIS proxy %s %s -> status=%s",
            method, params.get("m") if params else path, response.status_code,
        )

        json_data = _try_json(response)
        if json_data is not None:
            return json_data

        if _is_html_content(response):
            logger.warning("MIS proxy returned HTML (status=%s)", response.status_code)
            raise MisHtmlError(_describe_html(response.text))

        logger.warning("MIS proxy non-JSON non-HTML: %.300s", response.text)
        return {"raw_text": response.text}

    async def ensure_session(
        self,
        login: str,
        password: str | None,
        redis_con: Redis,
        user_id: str,
    ) -> MisSession | None:
        if not password:
            return None
        session = await self.authenticate(login, password)
        await delete_mis_session(redis_con, user_id)
        await session.save(redis_con, user_id)
        return session

    async def invalidate(
        self,
        redis_con: Redis,
        user_id: str,
        session: MisSession | None = None,
    ) -> None:
        """Выбросить сессию ЕЦП: из Redis и, по возможности, на стороне ЕЦП."""
        await delete_mis_session(redis_con, user_id)
        if session is None:
            return
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=min(10, settings.mis_request_timeout),
                follow_redirects=True,
            ) as client:
                await client.get(
                    LOGOUT_PATH,
                    params={"Sess_id": session.sess_id},
                    cookies=session.cookies,
                    headers=self._headers(),
                )
        except Exception as e:
            logger.debug("MIS logout call failed (ignored): %s", e)

    async def aclose(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


mis_client = MisClient()