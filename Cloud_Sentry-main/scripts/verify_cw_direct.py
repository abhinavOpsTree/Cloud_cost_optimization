import os
from dotenv import load_dotenv
import boto3
from datetime import datetime, timedelta

def check_instances():
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
    
    instances = ['i-0example1234567890', 'i-0example0987654321']
# Replace with real instance IDs from your AWS account
    region = 'ap-south-1'
    print(f"Checking CloudWatch for data on instances: {instances}...")
    
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=30)
    
    cw = boto3.client('cloudwatch', region_name=region)
    
    for inst_id in instances:
        try:
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
            
            print(f"Instance: {inst_id} | CW Data Found: {has_real_cw_data} | Datapoints: {datapoints}")
        except Exception as e:
            print(f"Instance: {inst_id} | ERROR querying CloudWatch: {e}")

if __name__ == "__main__":
    check_instances()
