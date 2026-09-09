from typing import Any

import requests

from app.core.config import settings
from app.core.logger import get_logger


logger = get_logger("spendsmart.client")


class SpendSmartClient:
    def __init__(self):
        self.base_url = settings.spendsmart_base_url.rstrip("/")
        self.timeout = settings.spendsmart_timeout_seconds
        self.verify_ssl = settings.spendsmart_verify_ssl

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

        if settings.spendsmart_api_token.strip():
            self.session.headers["Authorization"] = (
                f"Bearer {settings.spendsmart_api_token.strip()}"
            )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        payload: dict | None = None,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"

        logger.info(
            "SpendSmart request | method=%s | path=%s | params=%s",
            method,
            path,
            params,
        )

        response = self.session.request(
            method=method,
            url=url,
            params=params,
            json=payload,
            timeout=self.timeout,
            verify=self.verify_ssl,
        )

        logger.info(
            "SpendSmart response | status=%s | path=%s",
            response.status_code,
            path,
        )

        response.raise_for_status()

        try:
            return response.json()
        except ValueError:
            return {
                "status_code": response.status_code,
                "text": response.text,
            }

    def get(self, path: str, params: dict | None = None):
        return self.request("GET", path, params=params)

    def post(self, path: str, payload: dict | None = None, params: dict | None = None):
        return self.request("POST", path, params=params, payload=payload)

    def put(self, path: str, payload: dict | None = None, params: dict | None = None):
        return self.request("PUT", path, params=params, payload=payload)

    def patch(self, path: str, payload: dict | None = None, params: dict | None = None):
        return self.request("PATCH", path, params=params, payload=payload)

    def delete(self, path: str, params: dict | None = None):
        return self.request("DELETE", path, params=params)
