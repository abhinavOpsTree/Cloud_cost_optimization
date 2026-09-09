from app.services.spendsmart.endpoint_registry import ENDPOINTS


def test_ec2_endpoints_present():
    assert ENDPOINTS["compute_ec2"]["summary"][1] == "/api/v1/compute/ec2/summary"
    assert ENDPOINTS["compute_ec2"]["instances"][1] == "/api/v1/compute/ec2/instances"
    assert ENDPOINTS["optimizations"]["ec2"][1] == "/api/v1/optimizations/compute/ec2"
