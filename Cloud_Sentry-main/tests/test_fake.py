from core.uniteconpro_client import get_ec2_lifecycle
import json

lc = get_ec2_lifecycle('i-fake1234')
print(f"Fake instance lifecycle returns: {json.dumps(lc)}")
