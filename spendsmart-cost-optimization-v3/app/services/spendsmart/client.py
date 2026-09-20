from __future__ import annotations

import logging
import time
from typing import Any

import requests

from app.core.config import settings
from app.core.logger import get_logger


logger = get_logger("spendsmart.client")


# ============================================================
# RETRY CONFIGURATION
# ============================================================

DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0

RETRYABLE_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}

RETRYABLE_METHODS = {
    "GET",
}


class SpendSmartClient:
    """
    HTTP client for SpendSmart / UnitEconPro.

    GET requests are retried for temporary upstream failures.

    POST/PUT/PATCH/DELETE requests are not automatically retried
    because they may have side effects.
    """

    def __init__(self):
        self.base_url = (
            settings.spendsmart_base_url.rstrip("/")
        )

        self.timeout = (
            settings.spendsmart_timeout_seconds
        )

        self.verify_ssl = (
            settings.spendsmart_verify_ssl
        )

        self.max_retries = DEFAULT_MAX_RETRIES

        self.retry_backoff_seconds = (
            DEFAULT_RETRY_BACKOFF_SECONDS
        )

        self.session = requests.Session()

        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

        if settings.spendsmart_api_token.strip():

            self.session.headers[
                "Authorization"
            ] = (
                "Bearer "
                f"{settings.spendsmart_api_token.strip()}"
            )

    # ========================================================
    # RETRY HELPERS
    # ========================================================

    def _should_retry_status(
        self,
        method: str,
        status_code: int,
    ) -> bool:
        """
        Return True when the HTTP response represents a
        temporary failure that is safe to retry.
        """

        return (
            method.upper() in RETRYABLE_METHODS
            and status_code in RETRYABLE_STATUS_CODES
        )

    def _should_retry_exception(
        self,
        method: str,
        exc: Exception,
    ) -> bool:
        """
        Retry GET requests for temporary network failures.
        """

        if method.upper() not in RETRYABLE_METHODS:
            return False

        return isinstance(
            exc,
            (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ),
        )

    def _retry_delay(
        self,
        retry_number: int,
    ) -> float:
        """
        Exponential backoff.

        retry_number=1 -> 1 second
        retry_number=2 -> 2 seconds
        """

        return (
            self.retry_backoff_seconds
            * (2 ** (retry_number - 1))
        )

    # ========================================================
    # REQUEST
    # ========================================================

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        payload: dict | None = None,
    ) -> Any:

        method = method.upper()

        url = (
            f"{self.base_url}/"
            f"{path.lstrip('/')}"
        )

        retry_enabled = (
            method in RETRYABLE_METHODS
        )

        max_attempts = (
            self.max_retries + 1
            if retry_enabled
            else 1
        )

        last_exception: Exception | None = None

        for attempt in range(
            1,
            max_attempts + 1,
        ):

            logger.info(
                (
                    "SpendSmart request | "
                    "method=%s | "
                    "path=%s | "
                    "params=%s | "
                    "attempt=%s/%s"
                ),
                method,
                path,
                params,
                attempt,
                max_attempts,
            )

            try:

                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=payload,
                    timeout=self.timeout,
                    verify=self.verify_ssl,
                )

            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as exc:

                last_exception = exc

                logger.warning(
                    (
                        "SpendSmart network failure | "
                        "method=%s | "
                        "path=%s | "
                        "attempt=%s/%s | "
                        "error=%s"
                    ),
                    method,
                    path,
                    attempt,
                    max_attempts,
                    exc,
                )

                should_retry = (
                    attempt < max_attempts
                    and self._should_retry_exception(
                        method,
                        exc,
                    )
                )

                if not should_retry:
                    raise

                delay = self._retry_delay(
                    attempt
                )

                logger.info(
                    (
                        "Retrying SpendSmart request | "
                        "path=%s | "
                        "retry_in_seconds=%.1f"
                    ),
                    path,
                    delay,
                )

                time.sleep(delay)

                continue

            logger.info(
                (
                    "SpendSmart response | "
                    "status=%s | "
                    "path=%s | "
                    "attempt=%s/%s"
                ),
                response.status_code,
                path,
                attempt,
                max_attempts,
            )

            # ------------------------------------------------
            # Retry temporary upstream HTTP failures
            # ------------------------------------------------

            if (
                attempt < max_attempts
                and self._should_retry_status(
                    method,
                    response.status_code,
                )
            ):

                delay = self._retry_delay(
                    attempt
                )

                logger.warning(
                    (
                        "Temporary SpendSmart failure | "
                        "status=%s | "
                        "path=%s | "
                        "retry_in_seconds=%.1f"
                    ),
                    response.status_code,
                    path,
                    delay,
                )

                time.sleep(delay)

                continue

            # ------------------------------------------------
            # Final HTTP validation
            # ------------------------------------------------

            response.raise_for_status()

            # ------------------------------------------------
            # Parse response
            # ------------------------------------------------

            try:

                return response.json()

            except ValueError:

                logger.warning(
                    (
                        "SpendSmart response is not JSON | "
                        "status=%s | "
                        "path=%s"
                    ),
                    response.status_code,
                    path,
                )

                return {
                    "status_code": (
                        response.status_code
                    ),
                    "text": response.text,
                }

        # ----------------------------------------------------
        # Defensive fallback
        # ----------------------------------------------------

        if last_exception is not None:
            raise last_exception

        raise RuntimeError(
            (
                "SpendSmart request failed without "
                f"a response | path={path}"
            )
        )

    # ========================================================
    # HTTP METHODS
    # ========================================================

    def get(
        self,
        path: str,
        params: dict | None = None,
    ):
        return self.request(
            "GET",
            path,
            params=params,
        )

    def post(
        self,
        path: str,
        payload: dict | None = None,
        params: dict | None = None,
    ):
        return self.request(
            "POST",
            path,
            params=params,
            payload=payload,
        )

    def put(
        self,
        path: str,
        payload: dict | None = None,
        params: dict | None = None,
    ):
        return self.request(
            "PUT",
            path,
            params=params,
            payload=payload,
        )

    def patch(
        self,
        path: str,
        payload: dict | None = None,
        params: dict | None = None,
    ):
        return self.request(
            "PATCH",
            path,
            params=params,
            payload=payload,
        )

    def delete(
        self,
        path: str,
        params: dict | None = None,
    ):
        return self.request(
            "DELETE",
            path,
            params=params,
        )