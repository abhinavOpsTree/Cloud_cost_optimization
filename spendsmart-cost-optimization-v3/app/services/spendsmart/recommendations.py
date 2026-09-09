from app.services.spendsmart.catalog_client import call_catalog_endpoint


def get_recommendations(params=None):
    return call_catalog_endpoint(
        "recommendations",
        "list",
        query_params=params,
    )


def get_recommendation_summary(params=None):
    return call_catalog_endpoint(
        "recommendations",
        "summary",
        query_params=params,
    )


def get_stateful_recommendations(params=None):
    return call_catalog_endpoint(
        "stateful_recommendations",
        "list",
        query_params=params,
    )


def get_stateful_recommendation_summary(params=None):
    return call_catalog_endpoint(
        "stateful_recommendations",
        "summary",
        query_params=params,
    )


def get_stateful_recommendation(rec_id: str):
    return call_catalog_endpoint(
        "stateful_recommendations",
        "detail",
        path_params={"rec_id": rec_id},
    )
