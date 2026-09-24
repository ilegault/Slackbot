import re

with open("tests/test_38_workday_path_approval.py", "r") as f:
    content = f.read()

content = content.replace(
    '"end_user": "Dylan",',
    '"end_user": "Dylan",\n        "name_of_system": "",\n        "asset_id": "",'
)

with open("tests/test_38_workday_path_approval.py", "w") as f:
    f.write(content)
