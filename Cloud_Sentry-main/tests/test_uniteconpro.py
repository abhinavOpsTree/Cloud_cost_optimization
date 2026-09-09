from core.uniteconpro_client import get_ec2_lifecycle, get_ec2_instance_metadata
import json

instances = ['i-0example1234567890', 'i-0example0987654321']
for i in instances:
    print(f"\n--- Instance: {i} ---")
    
    lc = get_ec2_lifecycle(i)
    print("Lifecycle Data:")
    print(json.dumps(lc, indent=2))
    
    md = get_ec2_instance_metadata(i)
    print("\nMetadata:")
    print(json.dumps(md, indent=2))
