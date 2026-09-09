from app.services.spendsmart.client import SpendSmartClient
from app.services.spendsmart.endpoint_registry import get_endpoint


def call_catalog_endpoint(
    group: str,
    name: str,
    *,
    path_params: dict | None = None,
    query_params: dict | None = None,
    payload: dict | None = None,
):
    method, path = get_endpoint(group, name)

    path_params = path_params or {}

    for key, value in path_params.items():
        path = path.replace(
            "{" + key + "}",
            str(value),
        )

    client = SpendSmartClient()

    return client.request(
        method,
        path,
        params=query_params,
        payload=payload,
    )
