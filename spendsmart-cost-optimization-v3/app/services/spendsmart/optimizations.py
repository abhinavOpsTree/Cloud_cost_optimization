from app.services.spendsmart.catalog_client import call_catalog_endpoint


def get_optimizations(params=None):
    return call_catalog_endpoint(
        "optimizations",
        "list",
        query_params=params,
    )


def get_optimization_summary(params=None):
    return call_catalog_endpoint(
        "optimizations",
        "summary",
        query_params=params,
    )


def get_ec2_optimizations(params=None):
    return call_catalog_endpoint(
        "optimizations",
        "ec2",
        query_params=params,
    )


def trigger_optimization_sync(payload=None):
    return call_catalog_endpoint(
        "optimizations",
        "sync",
        payload=payload,
    )
