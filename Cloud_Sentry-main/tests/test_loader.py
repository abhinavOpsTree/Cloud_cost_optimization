import os
from dotenv import load_dotenv
load_dotenv()

from core.live_data_loader import get_live_billing_df
import json

instances = ['i-0example1234567890', 'i-0example0987654321']
df = get_live_billing_df(instances)
print(df.to_dict('records'))
