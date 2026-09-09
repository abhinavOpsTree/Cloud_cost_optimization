import threading
import time
import pandas as pd
import logging
import concurrent.futures
from core.uniteconpro_client import get_full_ec2_data, get_all_ec2_instances
from core.cloudwatch_client import get_memory_and_swap_metrics

logger = logging.getLogger(__name__)

# UnitEconPro API only handles 1 concurrent request — confirmed by their team.
# All threads must hold this lock before calling get_full_ec2_data().
# CloudWatch has no known concurrency limit and remains outside this lock.
_uniteconpro_lock = threading.Lock()


def _fetch_uep_with_retry(instance_id, start_date=None, end_date=None, max_attempts=3):
    """
    Call get_full_ec2_data() under the serialization lock, with exponential backoff retry.

    Retry policy (matches llm_client.py style):
      - Attempt 1: immediate
      - Attempt 2: 1s backoff
      - Attempt 3: 2s backoff
    On all attempts exhausted, returns None (caller must handle gracefully).
    """
    last_exc = None
    for attempt in range(max_attempts):
        if attempt > 0:
            backoff = 2 ** (attempt - 1)  # 1s, 2s
            print(f"[UEP] Retrying {instance_id} (attempt {attempt + 1}/{max_attempts}) "
                  f"after {backoff}s backoff...")
            time.sleep(backoff)
        try:
            with _uniteconpro_lock:
                return get_full_ec2_data(instance_id, start_date=start_date, end_date=end_date)
        except Exception as e:
            last_exc = e
            print(f"[UEP] Attempt {attempt + 1} failed for {instance_id}: {e}")

    print(f"[UEP] All {max_attempts} attempts exhausted for {instance_id}. "
          f"Last error: {last_exc}")
    return None


def _process_single_instance(instance_id, region, start_date=None, end_date=None):
    try:
        # 1. Fetch metadata and lifecycle — SERIALIZED (UnitEconPro is single-threaded)
        #    Retried up to 3 times with exponential backoff on failure.
        uep_data = _fetch_uep_with_retry(instance_id, start_date=start_date, end_date=end_date)

        if uep_data is None:
            # UnitEconPro fetch failed all retries — mark row as incomplete so
            # downstream can explicitly exclude it rather than treating it as a
            # legitimate zero-cost/zero-usage instance.
            logger.error(
                f"[UEP] Fatal: all retries failed for {instance_id}. "
                f"Row will be excluded from analysis."
            )
            return {'resource_id': instance_id, 'data_fetch_failed': True}

        # 2. Fetch CloudWatch metrics — NOT serialized (no known concurrency limit)
        #    Runs concurrently across threads while others wait on _uniteconpro_lock.
        cw_data = get_memory_and_swap_metrics(instance_id, region=region)

        md = uep_data.get('metadata') or {}
        lc = uep_data.get('lifecycle') or {}

        row = {
            'linked_account_id': md.get('aws_account_id'),
            'account_name': md.get('account_name'),
            'service_name': 'Amazon Elastic Compute Cloud',
            'product_name': 'Compute Instance',
            'resource_id': instance_id,
            'resource_type': 'RunInstances',
            'unblended_cost': lc.get('total_cost', 0.0),
            'blended_cost': lc.get('total_cost', 0.0),
            'currency': 'USD',
            'usage_amount': lc.get('total_hours', 0.0),
            'usage_unit': 'Hrs',
            'usage_type': f"BoxUsage:{md.get('instance_type')}" if md.get('instance_type') else None,
            'operation': 'RunInstances',
            'usage_start_time': lc.get('first_seen'),
            'usage_end_time': None,
            'billing_period': None,
            'region': md.get('region'),
            'availability_zone': md.get('availability_zone'),
            'pricing_model': md.get('pricing_model'),
            'instance_type': md.get('instance_type'),
            'instance_family': md.get('instance_type', '').split('.')[0] if md.get('instance_type') else None,
            'cpu_avg_pct': md.get('cpu_avg_pct'),
            'cpu_max_pct': md.get('cpu_max_pct'),
            'cpu_p95_pct': md.get('cpu_p95_pct'),
            'net_in_mbps': md.get('net_in_mbps'),
            'net_out_mbps': md.get('net_out_mbps'),
            'rightsizing_signal': md.get('rightsizing_signal'),
            'environment': (md.get('tags') or {}).get('Environment'),
            'owner': (md.get('tags') or {}).get('owner'),
            'team': (md.get('tags') or {}).get('team'),
            'application_name': (md.get('tags') or {}).get('application'),
            'cost_center': None,
            'project': None,
            'resource_name': (md.get('tags') or {}).get('Name'),
            'all_tags': str(md.get('tags') or {}),
            'mem_avg_pct': (cw_data or {}).get('memory_avg_pct'),
            'swap_avg_pct': (cw_data or {}).get('swap_avg_pct'),
            'inferred_state': lc.get('inferred_state', 'Unknown'),
            'data_fetch_failed': False,
        }
        return row
    except Exception as e:
        # Unexpected error outside the UEP/CW calls — mark as failed rather than
        # returning a near-empty row that could be mistaken for a zero-cost instance.
        logger.error(f"Failed to process instance {instance_id}: {e}")
        return {'resource_id': instance_id, 'data_fetch_failed': True}


def get_live_billing_df(account="opstree", region="ap-south-1", days=90, start_date=None, end_date=None):
    from datetime import datetime, timedelta

    if not end_date:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    instances = get_all_ec2_instances(account, start_date=start_date, end_date=end_date)
    instance_ids = [inst.get("instance_id") for inst in instances if inst.get("instance_id")]

    rows = []
    logger.info(f"Fetching data for {len(instance_ids)} instances (UEP serialized, CW concurrent)...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(_process_single_instance, iid, region, start_date, end_date)
            for iid in instance_ids
        ]
        for future in concurrent.futures.as_completed(futures):
            rows.append(future.result())

    df = pd.DataFrame(rows)
    return df
