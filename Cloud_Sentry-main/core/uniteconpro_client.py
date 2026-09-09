import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

UNITECONPRO_API_BASE_URL = os.getenv("UNITECONPRO_API_BASE_URL", "https://uniteconpro-api.opstree.dev")
UNITECONPRO_API_KEY = os.getenv("UNITECONPRO_API_KEY", "")

def _get_headers():
    headers = {}
    if UNITECONPRO_API_KEY:
        headers["Authorization"] = f"Bearer {UNITECONPRO_API_KEY}"
    return headers

def get_ec2_lifecycle(instance_id, account="opstree", start_date=None, end_date=None):
    url = f"{UNITECONPRO_API_BASE_URL}/api/v1/compute/ec2/lifecycle"
    params = {
        "account": account,
        "instance_id": instance_id,
        "include_gaps": "true"
    }
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    try:
        response = requests.get(url, params=params, headers=_get_headers(), timeout=10)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and len(data) > 0:
            return data[0]
        return None
    except Exception as e:
        logger.error(f"Failed to fetch lifecycle for {instance_id}: {e}")
        return None

def get_ec2_instance_metadata(
    instance_id,
    start_date=None,
    end_date=None,
    account="All"
):
    url = (
        f"{UNITECONPRO_API_BASE_URL}"
        f"/api/v1/compute/ec2/instances/{instance_id}/metadata"
    )
    params = {"account": account}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    try:
        response = requests.get(
            url, params=params,
            headers=_get_headers(), timeout=10
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(
            f"Failed to fetch metadata for {instance_id}: {e}"
        )
        return None

def get_full_ec2_data(
    instance_id,
    account="opstree",
    start_date=None,
    end_date=None
):
    lifecycle = get_ec2_lifecycle(
        instance_id, account, start_date, end_date
    )
    metadata = get_ec2_instance_metadata(
        instance_id, start_date, end_date, account
    )
    return {
        "lifecycle": lifecycle,
        "metadata": metadata
    }

def get_all_ec2_instances(
    account="opstree",
    start_date=None,
    end_date=None,
    page_size=100
):
    """
    Fetches ALL EC2 instances with pagination.
    UnitEconPro default limit is 50 which misses
    instances beyond the first page.
    Loops until all pages are fetched.
    """
    url = f"{UNITECONPRO_API_BASE_URL}/api/v1/compute/ec2/instances"
    all_instances = []
    skip = 0

    while True:
        params = {
            "account": account,
            "limit": page_size,
            "skip": skip
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        try:
            response = requests.get(
                url, params=params,
                headers=_get_headers(), timeout=15
            )
            response.raise_for_status()
            page = response.json()
            if not page:
                break
            all_instances.extend(page)
            if len(page) < page_size:
                break
            skip += page_size
            logger.info(
                f"Fetched {len(all_instances)} instances so far..."
            )
        except Exception as e:
            logger.error(
                f"Failed to fetch instances page "
                f"(skip={skip}): {e}"
            )
            break

    logger.info(
        f"Total instances fetched: {len(all_instances)}"
    )
    return all_instances

def get_ec2_summary(account="opstree", start_date=None, end_date=None):
    url = f"{UNITECONPRO_API_BASE_URL}/api/v1/compute/ec2/summary"
    params = {"account": account}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    try:
        response = requests.get(url, params=params, headers=_get_headers(), timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch summary for account {account}: {e}")
        return None
