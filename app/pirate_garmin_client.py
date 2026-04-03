from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

CONNECT_API_BASE_URL = "https://connectapi.garmin.com"
DI_TOKEN_URL = "https://diauth.garmin.com/di-oauth2-service/oauth/token"
GARTH_CLIENT_ID = "GCM_ANDROID_DARK"
GARTH_LOGIN_URL = "https://mobile.integration.garmin.com/gcm/android"
DI_GRANT_TYPE = "https://connectapi.garmin.com/di-oauth2-service/oauth/grant/service_ticket"
DI_CLIENT_IDS = (
    "GARMIN_CONNECT_MOBILE_ANDROID_DI_2025Q2",
    "GARMIN_CONNECT_MOBILE_ANDROID_DI_2024Q4",
    "GARMIN_CONNECT_MOBILE_ANDROID_DI",
)
MOBILE_SSO_BASE_URL = "https://sso.garmin.com"
MOBILE_SSO_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; sdk_gphone64_arm64 Build/TE1A.220922.025; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/132.0.0.0 Mobile Safari/537.36"
)
NATIVE_API_USER_AGENT = "GCM-Android-5.23"
NATIVE_X_GARMIN_USER_AGENT = (
    "com.garmin.android.apps.connectmobile/5.23; ; Google/sdk_gphone64_arm64/google; "
    "Android/33; Dalvik/2.1.0"
)
DEFAULT_TIMEOUT_SECONDS = 30.0
TOKEN_EXPIRY_SAFETY_SECONDS = 300


class PirateGarminError(RuntimeError):
    pass


class BrowserDependencyError(PirateGarminError):
    pass


@dataclass
class OAuth2Token:
    token_type: str
    access_token: str
    refresh_token: str
    expires_in: int
    expires_at: int
    refresh_token_expires_in: int
    refresh_token_expires_at: int
    scope: str = ""
    jti: str | None = None
    customer_id: str | None = None

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> "OAuth2Token":
        now = int(time.time())
        expires_in = int(payload["expires_in"])
        refresh_expires_in = int(payload["refresh_token_expires_in"])
        return cls(
            scope=str(payload.get("scope", "")),
            token_type=str(payload["token_type"]),
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            expires_in=expires_in,
            expires_at=now + expires_in,
            refresh_token_expires_in=refresh_expires_in,
            refresh_token_expires_at=now + refresh_expires_in,
            jti=_optional_str(payload.get("jti")),
            customer_id=_optional_str(payload.get("customerId")),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OAuth2Token":
        return cls(
            scope=str(payload.get("scope", "")),
            token_type=str(payload["token_type"]),
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            expires_in=int(payload["expires_in"]),
            expires_at=int(payload["expires_at"]),
            refresh_token_expires_in=int(payload["refresh_token_expires_in"]),
            refresh_token_expires_at=int(payload["refresh_token_expires_at"]),
            jti=_optional_str(payload.get("jti")),
            customer_id=_optional_str(payload.get("customerId")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "scope": self.scope,
            "token_type": self.token_type,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_in": self.expires_in,
            "expires_at": self.expires_at,
            "refresh_token_expires_in": self.refresh_token_expires_in,
            "refresh_token_expires_at": self.refresh_token_expires_at,
        }
        if self.jti:
            payload["jti"] = self.jti
        if self.customer_id:
            payload["customerId"] = self.customer_id
        return payload


@dataclass
class NativeTokenSlot:
    client_id: str
    token: OAuth2Token

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NativeTokenSlot":
        return cls(
            client_id=str(payload["clientId"]),
            token=OAuth2Token.from_dict(payload["token"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "clientId": self.client_id,
            "token": self.token.to_dict(),
        }


@dataclass
class NativeOAuth2Session:
    created_at: str
    login_client_id: str
    service_url: str
    di: NativeTokenSlot

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NativeOAuth2Session":
        return cls(
            created_at=str(payload["createdAt"]),
            login_client_id=str(payload["loginClientId"]),
            service_url=str(payload["serviceUrl"]),
            di=NativeTokenSlot.from_dict(payload["di"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "createdAt": self.created_at,
            "loginClientId": self.login_client_id,
            "serviceUrl": self.service_url,
            "di": self.di.to_dict(),
        }


@dataclass
class FreshLoginResult:
    service_ticket: str


class PirateGarminAuthManager:
    def __init__(self, *, username: str, password: str, app_dir: str | Path, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self.username = username
        self.password = password
        self.app_dir = Path(app_dir).expanduser()
        self.timeout = timeout
        self.native_oauth2_path = self.app_dir / "native-oauth2.json"

    def load_native_session(self) -> NativeOAuth2Session | None:
        if not self.native_oauth2_path.exists():
            return None
        return NativeOAuth2Session.from_dict(json.loads(self.native_oauth2_path.read_text(encoding="utf-8")))

    def save_native_session(self, session: NativeOAuth2Session) -> None:
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.native_oauth2_path.write_text(json.dumps(session.to_dict(), indent=2) + "\n", encoding="utf-8")

    def ensure_authenticated(self, *, force_refresh: bool = False) -> NativeOAuth2Session:
        session = self.load_native_session()
        if session is None:
            session = self.create_native_session()
            self.save_native_session(session)
            return session
        if force_refresh or _token_needs_refresh(session.di.token):
            if force_refresh and not _refresh_token_expired(session.di.token):
                refreshed_slot = self.refresh_di_token_slot(session.di)
                session = NativeOAuth2Session(
                    created_at=_utc_now_iso(),
                    login_client_id=session.login_client_id,
                    service_url=session.service_url,
                    di=refreshed_slot,
                )
            elif _refresh_token_expired(session.di.token):
                session = self.create_native_session()
            else:
                session = NativeOAuth2Session(
                    created_at=_utc_now_iso(),
                    login_client_id=session.login_client_id,
                    service_url=session.service_url,
                    di=self.refresh_di_token_slot(session.di),
                )
            self.save_native_session(session)
        return session

    def create_native_session(self, *, headless: bool = False) -> NativeOAuth2Session:
        fresh = login_via_browser(
            username=self.username,
            password=self.password,
            timeout=self.timeout,
            headless=headless,
        )
        with httpx.Client(follow_redirects=True, timeout=self.timeout) as client:
            di_slot = self.exchange_service_ticket_for_di_token(client, fresh.service_ticket, DI_CLIENT_IDS)
        return NativeOAuth2Session(
            created_at=_utc_now_iso(),
            login_client_id=GARTH_CLIENT_ID,
            service_url=GARTH_LOGIN_URL,
            di=di_slot,
        )

    def exchange_service_ticket_for_di_token(
        self,
        client: httpx.Client,
        service_ticket: str,
        client_ids: tuple[str, ...] | list[str],
    ) -> NativeTokenSlot:
        errors: list[str] = []
        for client_id in client_ids:
            response = client.post(
                DI_TOKEN_URL,
                headers=build_native_headers(
                    {
                        "authorization": _build_basic_authorization_header(client_id),
                        "accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                        "content-type": "application/x-www-form-urlencoded",
                        "cache-control": "no-cache",
                        "connection": "keep-alive",
                    }
                ),
                data={
                    "client_id": client_id,
                    "service_ticket": service_ticket,
                    "grant_type": DI_GRANT_TYPE,
                    "service_url": GARTH_LOGIN_URL,
                },
            )
            if response.status_code == 429:
                raise PirateGarminError(f"Garmin native DI token exchange returned 429 for {client_id}")
            if not response.is_success:
                errors.append(f"{client_id}: {response.status_code} {_safe_snippet(response.text)}")
                continue
            try:
                token = OAuth2Token.from_response(response.json())
            except Exception:
                errors.append(f"{client_id}: unexpected non-token response {_safe_snippet(response.text)}")
                continue
            return NativeTokenSlot(client_id=client_id, token=token)
        raise PirateGarminError("Garmin native DI token exchange failed:\n" + "\n".join(errors))

    def refresh_di_token_slot(self, slot: NativeTokenSlot) -> NativeTokenSlot:
        with httpx.Client(follow_redirects=True, timeout=self.timeout) as client:
            response = client.post(
                DI_TOKEN_URL,
                headers=build_native_headers(
                    {
                        "authorization": _build_basic_authorization_header(slot.client_id),
                        "accept": "application/json",
                        "content-type": "application/x-www-form-urlencoded",
                        "cache-control": "no-cache",
                        "connection": "keep-alive",
                    }
                ),
                data={
                    "grant_type": "refresh_token",
                    "client_id": slot.client_id,
                    "refresh_token": slot.token.refresh_token,
                },
            )
        if response.status_code == 429:
            raise PirateGarminError(f"Garmin native DI refresh returned 429 for {slot.client_id}")
        if not response.is_success:
            raise PirateGarminError(
                f"Native Garmin DI refresh failed: {response.status_code} {_safe_snippet(response.text)}"
            )
        return NativeTokenSlot(client_id=slot.client_id, token=OAuth2Token.from_response(response.json()))


def default_app_dir() -> Path:
    configured = os.environ.get("PIRATE_GARMIN_APP_DIR")
    if configured:
        return Path(configured).expanduser()
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / "pirate-garmin"
    return Path.home() / ".local" / "share" / "pirate-garmin"


def list_activities(
    *,
    username: str,
    password: str,
    app_dir: str | Path,
    start_date: str,
    end_date: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    auth = PirateGarminAuthManager(username=username, password=password, app_dir=app_dir, timeout=timeout)
    session = auth.ensure_authenticated()
    access_token = session.di.token.access_token
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        response = client.get(
            f"{CONNECT_API_BASE_URL}/activitylist-service/activities/search/activities",
            headers=build_native_headers(
                {
                    "authorization": f"Bearer {access_token}",
                    "accept": "application/json",
                }
            ),
            params={
                "start": 0,
                "limit": 100,
                "startDate": start_date,
                "endDate": end_date,
            },
        )
    if response.status_code == 401:
        session = auth.ensure_authenticated(force_refresh=True)
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            response = client.get(
                f"{CONNECT_API_BASE_URL}/activitylist-service/activities/search/activities",
                headers=build_native_headers(
                    {
                        "authorization": f"Bearer {session.di.token.access_token}",
                        "accept": "application/json",
                    }
                ),
                params={
                    "start": 0,
                    "limit": 100,
                    "startDate": start_date,
                    "endDate": end_date,
                },
            )
    if response.status_code == 429:
        raise PirateGarminError("Garmin activity search returned 429")
    if not response.is_success:
        raise PirateGarminError(f"Garmin activity search failed: {response.status_code} {_safe_snippet(response.text)}")
    payload = response.json()
    return payload if isinstance(payload, list) else []


def bootstrap_with_browser(*, username: str, password: str, app_dir: str | Path, headless: bool = False) -> Path:
    auth = PirateGarminAuthManager(username=username, password=password, app_dir=app_dir)
    session = auth.create_native_session(headless=headless)
    auth.save_native_session(session)
    return auth.native_oauth2_path


def login_via_browser(
    username: str,
    password: str,
    timeout: float,
    client_id: str = GARTH_CLIENT_ID,
    service_url: str = GARTH_LOGIN_URL,
    user_agent: str = MOBILE_SSO_USER_AGENT,
    headless: bool = False,
) -> FreshLoginResult:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserDependencyError("Fresh Garmin login requires Playwright and Chromium.") from exc

    timeout_ms = max(int(timeout * 1000), 1000)
    sign_in_url = build_sign_in_url(client_id, service_url)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=user_agent,
            locale="en-US",
            viewport={"width": 412, "height": 915},
            is_mobile=True,
            has_touch=True,
        )
        captured_results: list[dict[str, Any]] = []
        context.expose_binding(
            "pirateGarminCaptureLogin",
            lambda _source, payload: captured_results.append(payload),
        )
        page = context.new_page()
        page.on("response", lambda response: _maybe_capture_network_response(response, captured_results))
        page.add_init_script(_login_capture_init_script())
        try:
            page.goto(sign_in_url, wait_until="load", timeout=timeout_ms)
            _fill_first(page, USERNAME_SELECTORS, username, timeout_ms, PlaywrightError)
            _fill_first(page, PASSWORD_SELECTORS, password, timeout_ms, PlaywrightError)
            _submit_login_form(page, timeout_ms, PlaywrightError)
            capture = _wait_for_captured_login_result(page, captured_results, timeout_ms, PlaywrightTimeoutError)
            return _parse_captured_login_result(capture)
        except PlaywrightTimeoutError as exc:
            raise PirateGarminError(
                "Timed out waiting for Garmin mobile login result. "
                f"Current page: {page.url}. Page snippet: {_page_snippet(page)}"
            ) from exc
        except PlaywrightError as exc:
            raise PirateGarminError(f"Garmin browser login automation failed: {exc}") from exc
        finally:
            context.close()
            browser.close()


USERNAME_SELECTORS = (
    'input[name="username"]',
    'input[name="email"]',
    'input[type="email"]',
    "#username",
)
PASSWORD_SELECTORS = (
    'input[name="password"]',
    'input[type="password"]',
    "#password",
)
SUBMIT_SELECTORS = (
    'button[type="submit"]',
    'button:has-text("Sign In")',
    'button:has-text("Log In")',
    'input[type="submit"]',
)


def build_sign_in_url(client_id: str, service_url: str) -> str:
    return (
        f"{MOBILE_SSO_BASE_URL}/mobile/sso/en_US/sign-in?"
        + urlencode({"clientId": client_id, "service": service_url})
    )


def build_native_headers(extra_headers: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "user-agent": NATIVE_API_USER_AGENT,
        "x-garmin-user-agent": NATIVE_X_GARMIN_USER_AGENT,
        "accept-language": "en-US,en;q=0.9",
        "origin": "https://sso.garmin.com",
    }
    if extra_headers:
        headers.update(extra_headers)
    return headers


def parse_login_response_payload(payload: dict[str, Any]) -> FreshLoginResult:
    response_status = payload.get("responseStatus")
    response_type = ""
    if isinstance(response_status, dict):
        raw_type = response_status.get("type")
        response_type = str(raw_type).upper() if raw_type else ""
    service_ticket = payload.get("serviceTicketId")
    if response_type == "SUCCESSFUL" and service_ticket:
        return FreshLoginResult(service_ticket=str(service_ticket))
    serialized = _serialize_payload(payload)
    if response_type == "CAPTCHA_REQUIRED":
        raise PirateGarminError(f"Garmin browser login requires CAPTCHA: {serialized}")
    if "MFA" in response_type or "TWO_FACTOR" in response_type:
        raise PirateGarminError(f"Garmin browser login requires MFA: {serialized}")
    if response_type:
        raise PirateGarminError(f"Garmin browser login failed ({response_type}): {serialized}")
    raise PirateGarminError(f"Garmin browser login returned unexpected payload: {serialized}")


def _fill_first(page: Any, selectors: tuple[str, ...], value: str, timeout_ms: int, playwright_error: type[Exception]) -> None:
    locator = _first_visible_locator(page, selectors, timeout_ms, playwright_error)
    if locator is None:
        raise PirateGarminError(f"Could not find Garmin login field. Tried selectors: {', '.join(selectors)}")
    locator.fill(value)


def _submit_login_form(page: Any, timeout_ms: int, playwright_error: type[Exception]) -> None:
    locator = _first_visible_locator(page, SUBMIT_SELECTORS, timeout_ms, playwright_error)
    if locator is not None:
        locator.click()
        return
    password_locator = _first_visible_locator(page, PASSWORD_SELECTORS, timeout_ms, playwright_error)
    if password_locator is None:
        raise PirateGarminError("Could not find Garmin password field to submit the login form")
    password_locator.press("Enter")


def _first_visible_locator(page: Any, selectors: tuple[str, ...], timeout_ms: int, playwright_error: type[Exception]) -> Any | None:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=750)
            except playwright_error:
                continue
            return locator
    return None


def _wait_for_captured_login_result(
    page: Any,
    captured_results: list[dict[str, Any]],
    timeout_ms: int,
    playwright_timeout_error: type[Exception],
) -> dict[str, Any]:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        if captured_results:
            return captured_results[-1]
        page.wait_for_timeout(200)
    raise playwright_timeout_error("Timed out waiting for captured Garmin login result")


def _maybe_capture_network_response(response: Any, captured_results: list[dict[str, Any]]) -> None:
    try:
        url = str(response.url or "")
        if "/mobile/api/login" not in url:
            return
        text = response.text()
        payload = None
        if text:
            try:
                payload = json.loads(text)
            except Exception:
                payload = None
        captured_results.append(
            {
                "status": response.status,
                "url": url,
                "text": text,
                "payload": payload,
            }
        )
    except Exception:
        return


def _parse_captured_login_result(capture: Any) -> FreshLoginResult:
    if not isinstance(capture, dict):
        raise PirateGarminError("Garmin browser login did not produce a capturable result")
    status = capture.get("status")
    response_text = str(capture.get("text") or "")
    payload = capture.get("payload")
    if status is not None and int(status) >= 400:
        raise PirateGarminError(
            f"Garmin browser login failed with HTTP {status}: {_safe_snippet(response_text)}"
        )
    if isinstance(payload, dict):
        return parse_login_response_payload(payload)
    if response_text:
        raise PirateGarminError(f"Garmin browser login returned a non-JSON response: {_safe_snippet(response_text)}")
    raise PirateGarminError("Garmin browser login returned an empty response")


def _login_capture_init_script() -> str:
    return """
(() => {
  if (window.__pirateGarminLoginHookInstalled) {
    return;
  }
  window.__pirateGarminLoginHookInstalled = true;

  const isLoginUrl = (url) => String(url || '').includes('/mobile/api/login');
  const setCapture = (status, url, text) => {
    let payload = null;
    if (typeof text === 'string' && text.length > 0) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = null;
      }
    }
    window.__pirateGarminLoginCapture = {
      status,
      url: String(url || ''),
      text: String(text || ''),
      payload,
    };
    if (typeof window.pirateGarminCaptureLogin === 'function') {
      void window.pirateGarminCaptureLogin(window.__pirateGarminLoginCapture);
    }
  };

  const originalFetch = window.fetch;
  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    try {
      const resource = args[0];
      const url = typeof resource === 'string' ? resource : resource && resource.url;
      if (isLoginUrl(url)) {
        const text = await response.clone().text();
        setCapture(response.status, url, text);
      }
    } catch (error) {
      window.__pirateGarminLoginCapture = {
        status: 599,
        url: '',
        text: String(error),
        payload: null,
      };
      if (typeof window.pirateGarminCaptureLogin === 'function') {
        void window.pirateGarminCaptureLogin(window.__pirateGarminLoginCapture);
      }
    }
    return response;
  };

  const OriginalXHR = window.XMLHttpRequest;
  if (OriginalXHR) {
    function WrappedXHR() {
      const xhr = new OriginalXHR();
      let requestUrl = '';
      const originalOpen = xhr.open;
      xhr.open = function(method, url, ...rest) {
        requestUrl = String(url || '');
        return originalOpen.call(this, method, url, ...rest);
      };
      xhr.addEventListener('load', () => {
        try {
          if (isLoginUrl(requestUrl)) {
            setCapture(xhr.status, requestUrl, xhr.responseText || '');
          }
        } catch (error) {
          window.__pirateGarminLoginCapture = {
            status: 599,
            url: requestUrl,
            text: String(error),
            payload: null,
          };
          if (typeof window.pirateGarminCaptureLogin === 'function') {
            void window.pirateGarminCaptureLogin(window.__pirateGarminLoginCapture);
          }
        }
      });
      return xhr;
    }
    WrappedXHR.UNSENT = OriginalXHR.UNSENT;
    WrappedXHR.OPENED = OriginalXHR.OPENED;
    WrappedXHR.HEADERS_RECEIVED = OriginalXHR.HEADERS_RECEIVED;
    WrappedXHR.LOADING = OriginalXHR.LOADING;
    WrappedXHR.DONE = OriginalXHR.DONE;
    WrappedXHR.prototype = OriginalXHR.prototype;
    window.XMLHttpRequest = WrappedXHR;
  }
})();
"""


def _build_basic_authorization_header(client_id: str) -> str:
    token = base64.b64encode(f"{client_id}:".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _safe_snippet(text: str, limit: int = 240) -> str:
    return " ".join((text or "").split())[:limit]


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _serialize_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


def _token_needs_refresh(token: OAuth2Token) -> bool:
    return token.expires_at <= int(time.time()) + TOKEN_EXPIRY_SAFETY_SECONDS


def _refresh_token_expired(token: OAuth2Token) -> bool:
    return token.refresh_token_expires_at <= int(time.time()) + TOKEN_EXPIRY_SAFETY_SECONDS


def _page_snippet(page: Any, limit: int = 240) -> str:
    try:
        content = page.content()
    except Exception:
        return "<unavailable>"
    return " ".join(content.split())[:limit]
