from app.services.spendsmart.catalog_client import call_catalog_endpoint


def get_ec2_summary(params: dict | None = None):
    return call_catalog_endpoint(
        "compute_ec2",
        "summary",
        query_params=params,
    )


def get_ec2_instances(params: dict | None = None):
    return call_catalog_endpoint(
        "compute_ec2",
        "instances",
        query_params=params,
    )


def get_ec2_lifecycle(params: dict | None = None):
    return call_catalog_endpoint(
        "compute_ec2",
        "lifecycle",
        query_params=params,
    )


def get_ec2_amis(params: dict | None = None):
    return call_catalog_endpoint(
        "compute_ec2",
        "amis",
        query_params=params,
    )


def get_ec2_instance_metadata(
    instance_id: str,
    params: dict | None = None,
):
    return call_catalog_endpoint(
        "compute_ec2",
        "instance_metadata",
        path_params={"instance_id": instance_id},
        query_params=params,
    )
