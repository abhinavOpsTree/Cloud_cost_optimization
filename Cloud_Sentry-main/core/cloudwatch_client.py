import logging
import boto3
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

def get_memory_and_swap_metrics(instance_id, region="ap-south-1"):
    result = {"memory_avg_pct": None, "swap_avg_pct": None}
    try:
        client = boto3.client('cloudwatch', region_name=region)
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=30)
        
        # Helper to fetch and average a metric
        def fetch_avg(metric_name):
            response = client.get_metric_statistics(
                Namespace='CWAgent',
                MetricName=metric_name,
                Dimensions=[
                    {
                        'Name': 'InstanceId',
                        'Value': instance_id
                    },
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=86400,
                Statistics=['Average']
            )
            datapoints = response.get('Datapoints', [])
            if not datapoints:
                return None
            
            total = sum(dp['Average'] for dp in datapoints)
            return total / len(datapoints)
        
        result["memory_avg_pct"] = fetch_avg("mem_used_percent")
        result["swap_avg_pct"] = fetch_avg("swap_used_percent")
        
        return result
    except Exception as e:
        logger.error(f"Failed to fetch CloudWatch metrics for {instance_id}: {e}")
        return result
