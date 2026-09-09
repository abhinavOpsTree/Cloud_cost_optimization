import os
import sys
# add parent to path so it can import core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.live_data_loader import get_live_billing_df
import boto3
from datetime import datetime, timedelta

def check_instances():
    print("Fetching instances from live_data_loader...")
    try:
        df = get_live_billing_df()
    except Exception as e:
        print(f"Error fetching from live_data_loader: {e}")
        return
        
    if df.empty:
        print("No instances found from live_data_loader.")
        return

    covered = df[df["cpu_avg_pct"].notna()]
    if covered.empty:
        print("No instances with cpu_avg_pct found in the DF.")
        return
        
    print(f"Found {len(covered)} covered instances. Checking CloudWatch for data...")
    
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=30)
    
    for _, row in covered.iterrows():
        inst_id = row['resource_id']
        region = row.get('region', 'ap-south-1')
        
        try:
            cw = boto3.client('cloudwatch', region_name=region)
            
            response = cw.get_metric_statistics(
                Namespace='AWS/EC2',
                MetricName='CPUUtilization',
                Dimensions=[{'Name': 'InstanceId', 'Value': inst_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=3600*24*30,
                Statistics=['Average']
            )
            
            datapoints = response.get('Datapoints', [])
            has_real_cw_data = len(datapoints) > 0
            
            print(f"Instance: {inst_id} | Region: {region} | UEP cpu_avg_pct: {row['cpu_avg_pct']} | CW Data Found: {has_real_cw_data} | Datapoints: {datapoints}")
        except Exception as e:
            print(f"Instance: {inst_id} | Region: {region} | ERROR querying CloudWatch: {e}")

if __name__ == "__main__":
    check_instances()
