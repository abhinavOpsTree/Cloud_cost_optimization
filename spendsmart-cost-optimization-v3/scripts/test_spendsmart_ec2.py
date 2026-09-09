from app.services.spendsmart.compute.ec2 import (
    get_ec2_amis,
    get_ec2_instances,
    get_ec2_lifecycle,
    get_ec2_summary,
)
from app.services.spendsmart.optimizations import (
    get_ec2_optimizations,
)


def main():
    print("===== SPENDSMART EC2 SOURCE TEST =====")

    print("Summary:")
    print(get_ec2_summary())

    print("Instances:")
    print(type(get_ec2_instances()).__name__)

    print("Lifecycle:")
    print(type(get_ec2_lifecycle()).__name__)

    print("AMIs:")
    print(type(get_ec2_amis()).__name__)

    print("EC2 Optimizations:")
    print(type(get_ec2_optimizations()).__name__)

    print("===== TEST COMPLETE =====")


if __name__ == "__main__":
    main()
