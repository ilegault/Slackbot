import re

with open("tests/test_08_assignment.py", "r") as f:
    content = f.read()

content = content.replace(
    'assert "Hirst Lab purchase request" in dm_calls[0][1]["text"]',
    'assert "Place this in Workday:" in dm_calls[0][1]["text"]'
)

with open("tests/test_08_assignment.py", "w") as f:
    f.write(content)

with open("tests/test_30_buyers_dm_carries_bom.py", "r") as f:
    content = f.read()

content = content.replace(
    'parsed=_parsed(total_price=150.0)',
    'parsed=_parsed(total_price=150.0, route="epif")'
)
# Make sure we change the mock of finding the card
content = content.replace(
    '"item_description": "Shaft Couplings",',
    '"item_description": "Shaft Couplings",\n        "route": "epif",'
)
content = content.replace(
    '"item_description": "Couplings",',
    '"item_description": "Couplings",\n        "route": "epif",'
)
content = content.replace(
    '"item_description": "Ruland Collars",',
    '"item_description": "Ruland Collars",\n        "route": "epif",'
)

with open("tests/test_30_buyers_dm_carries_bom.py", "w") as f:
    f.write(content)
