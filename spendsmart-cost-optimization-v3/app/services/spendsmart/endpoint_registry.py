"""
Endpoint catalog extracted from the provided UnitEconPro Swagger PDF.

This file catalogs the source API.
Only EC2 endpoints are currently processed downstream.
"""

ENDPOINTS = {
    "health": {
        "healthz": ("GET", "/api/v1/healthz"),
        "readyz": ("GET", "/api/v1/readyz"),
    },

    "dashboard": {
        "summary": ("GET", "/api/v1/dashboard/summary"),
        "trend": ("GET", "/api/v1/dashboard/trend"),
        "service_breakdown": ("GET", "/api/v1/dashboard/breakdown/service"),
        "comparison": ("GET", "/api/v1/dashboard/comparison"),
        "forecast": ("GET", "/api/v1/dashboard/forecast"),
    },

    "analytics": {
        "financials": ("GET", "/api/v1/analytics/financials"),
        "trend": ("GET", "/api/v1/analytics/trend"),
        "breakdown": ("GET", "/api/v1/analytics/breakdown"),
        "tag_breakdown": ("GET", "/api/v1/analytics/tag-breakdown"),
        "annotations_list": ("GET", "/api/v1/analytics/annotations"),
        "annotations_create": ("POST", "/api/v1/analytics/annotations"),
        "annotation_dates": ("GET", "/api/v1/analytics/annotation-dates"),
        "annotations_update": ("PUT", "/api/v1/analytics/annotations/{annotation_id}"),
        "annotations_delete": ("DELETE", "/api/v1/analytics/annotations/{annotation_id}"),
    },

    "compute_ec2": {
        "summary": ("GET", "/api/v1/compute/ec2/summary"),
        "instances": ("GET", "/api/v1/compute/ec2/instances"),
        "lifecycle": ("GET", "/api/v1/compute/ec2/lifecycle"),
        "amis": ("GET", "/api/v1/compute/ec2/amis"),
        "instance_metadata": ("GET", "/api/v1/compute/ec2/instances/{instance_id}/metadata"),
    },

    "compute_ecr": {
        "summary": ("GET", "/api/v1/compute/ecr/summary"),
        "repositories": ("GET", "/api/v1/compute/ecr/repositories"),
        "repository_metadata": ("GET", "/api/v1/compute/ecr/repositories/{repository_name}/metadata"),
    },

    "compute_eks": {
        "summary": ("GET", "/api/v1/compute/eks/summary"),
        "clusters": ("GET", "/api/v1/compute/eks/clusters"),
        "cluster_metadata": ("GET", "/api/v1/compute/eks/clusters/{cluster_name}/metadata"),
    },

    "compute_ecs": {
        "summary": ("GET", "/api/v1/compute/ecs/summary"),
        "clusters": ("GET", "/api/v1/compute/ecs/clusters"),
        "cluster_metadata": ("GET", "/api/v1/compute/ecs/clusters/{cluster_name}/metadata"),
    },

    "storage_s3": {
        "summary": ("GET", "/api/v1/storage/s3/summary"),
        "buckets": ("GET", "/api/v1/storage/s3/buckets"),
        "bucket_metadata": ("GET", "/api/v1/storage/s3/buckets/{bucket_name}/metadata"),
    },

    "storage_ebs": {
        "summary": ("GET", "/api/v1/storage/ebs/summary"),
        "volumes": ("GET", "/api/v1/storage/ebs/volumes"),
        "snapshots": ("GET", "/api/v1/storage/ebs/snapshots"),
        "volume_metadata": ("GET", "/api/v1/storage/ebs/volumes/{volume_id}/metadata"),
    },

    "databases_rds": {
        "summary": ("GET", "/api/v1/databases/rds/summary"),
        "instances": ("GET", "/api/v1/databases/rds/instances"),
        "snapshots": ("GET", "/api/v1/databases/rds/snapshots"),
        "instance_metadata": ("GET", "/api/v1/databases/rds/instances/{db_instance_id}/metadata"),
    },

    "networking_vpc": {
        "summary": ("GET", "/api/v1/networking/vpc/summary"),
        "public_ip_breakdown": ("GET", "/api/v1/networking/vpc/breakdown/public-ip"),
        "vpcs": ("GET", "/api/v1/networking/vpc/vpcs"),
        "metadata": ("GET", "/api/v1/networking/vpc/{vpc_id}/metadata"),
    },

    "networking_elb": {
        "summary": ("GET", "/api/v1/networking/elb/summary"),
        "load_balancers": ("GET", "/api/v1/networking/elb/lbs"),
        "gwlb_endpoints": ("GET", "/api/v1/networking/elb/gwlb-endpoints"),
        "metadata": ("GET", "/api/v1/networking/elb/lbs/{lb_arn}/metadata"),
    },

    "networking_datatransfer": {
        "summary": ("GET", "/api/v1/networking/datatransfer/summary"),
        "resources": ("GET", "/api/v1/networking/datatransfer/resources"),
    },

    "monitoring_cloudwatch": {
        "summary": ("GET", "/api/v1/monitoring/cloudwatch/summary"),
        "eks_clusters": ("GET", "/api/v1/monitoring/cloudwatch/eks-clusters"),
        "log_groups": ("GET", "/api/v1/monitoring/cloudwatch/log-groups"),
    },

    "budget": {
        "summary": ("GET", "/api/v1/budget/summary"),
        "recommend": ("GET", "/api/v1/budget/recommend"),
        "tags": ("GET", "/api/v1/budget/tags"),
        "create": ("POST", "/api/v1/budget/{account_name}"),
        "delete": ("DELETE", "/api/v1/budget/{account_name}"),
        "list": ("GET", "/api/v1/budget/{account_name}/list"),
        "thresholds_get": ("GET", "/api/v1/budget/{account_name}/thresholds"),
        "thresholds_put": ("PUT", "/api/v1/budget/{account_name}/thresholds"),
        "paused": ("PUT", "/api/v1/budget/{account_name}/paused"),
        "history": ("GET", "/api/v1/budget/{account_name}/history"),
    },

    "accounts": {
        "create": ("POST", "/api/v1/accounts/"),
        "list": ("GET", "/api/v1/accounts/"),
        "delete": ("DELETE", "/api/v1/accounts/{account_id}"),
        "validate": ("POST", "/api/v1/accounts/{account_id}/validate"),
    },

    "account_access": {
        "list": ("GET", "/api/v1/accounts/{account_id}/access"),
        "grant": ("POST", "/api/v1/accounts/{account_id}/access"),
        "revoke": ("DELETE", "/api/v1/accounts/{account_id}/access/{email}"),
    },

    "optimizations": {
        "list": ("GET", "/api/v1/optimizations/"),
        "sync": ("POST", "/api/v1/optimizations/sync"),
        "summary": ("GET", "/api/v1/optimizations/summary"),
        "ec2": ("GET", "/api/v1/optimizations/compute/ec2"),
    },

    "settings": {
        "get": ("GET", "/api/v1/settings/"),
        "update": ("PUT", "/api/v1/settings/"),
    },

    "permissions": {
        "list": ("GET", "/api/v1/permissions/"),
        "upsert": ("POST", "/api/v1/permissions/"),
        "account": ("GET", "/api/v1/permissions/{account_id}"),
        "delete": ("DELETE", "/api/v1/permissions/{account_id}/{service}"),
    },

    "alerts": {
        "dashboard": ("GET", "/api/v1/alerts/dashboard"),
        "by_account_service": ("GET", "/api/v1/alerts/by-account/{account_name}/service/{service}"),
        "detail": ("GET", "/api/v1/alerts/{alert_id}"),
    },

    "alert_rules": {
        "list": ("GET", "/api/v1/alerts/rules/"),
        "create": ("POST", "/api/v1/alerts/rules/"),
        "delete": ("DELETE", "/api/v1/alerts/rules/{rule_id}"),
    },

    "comparison": {
        "summary": ("GET", "/api/v1/comparison/summary"),
        "detail": ("GET", "/api/v1/comparison/detail"),
        "dates": ("GET", "/api/v1/comparison/dates"),
    },

    "report": {
        "summary": ("GET", "/api/v1/report/summary"),
        "trend": ("GET", "/api/v1/report/trend"),
    },

    "suggestions": {
        "list": ("GET", "/api/v1/suggestions"),
        "create": ("POST", "/api/v1/suggestions"),
        "update": ("PUT", "/api/v1/suggestions/{suggestion_id}"),
        "delete": ("DELETE", "/api/v1/suggestions/{suggestion_id}"),
    },

    "recommendations": {
        "list": ("GET", "/api/v1/recommendations"),
        "summary": ("GET", "/api/v1/recommendations/summary"),
    },

    "stateful_recommendations": {
        "status": ("PATCH", "/api/v1/stateful/recommendations/{rec_id}/status"),
        "list": ("GET", "/api/v1/stateful/recommendations"),
        "summary": ("GET", "/api/v1/stateful/recommendations/summary"),
        "purge": ("DELETE", "/api/v1/stateful/recommendations/purge"),
        "sync": ("POST", "/api/v1/stateful/recommendations/sync"),
        "detail": ("GET", "/api/v1/stateful/recommendations/{rec_id}"),
    },
}


def get_endpoint(group: str, name: str) -> tuple[str, str]:
    return ENDPOINTS[group][name]


def list_groups() -> list[str]:
    return sorted(ENDPOINTS.keys())


def list_endpoints(group: str | None = None):
    if group:
        return ENDPOINTS[group]
    return ENDPOINTS
