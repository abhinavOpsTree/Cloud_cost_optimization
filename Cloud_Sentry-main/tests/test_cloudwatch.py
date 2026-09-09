import os
from dotenv import load_dotenv
load_dotenv()

from core.cloudwatch_client import get_memory_and_swap_metrics
import json

instances = ['i-0example1234567890', 'i-0example0987654321']
for i in instances:
    print(f"\n--- Instance: {i} ---")
    data = get_memory_and_swap_metrics(i)
    print(json.dumps(data, indent=2))
