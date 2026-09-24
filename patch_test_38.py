import re

with open("tests/test_38_workday_path_approval.py", "r") as f:
    content = f.read()

content = content.replace(
    '"link": "https://fisher.com/item/123",',
    '"link": "https://fisher.com/item/123",\n        "purpose": "Need a laser mount",\n        "pi_of_funding": "Charlie Hirst",\n        "end_user": "Dylan",'
)

with open("tests/test_38_workday_path_approval.py", "w") as f:
    f.write(content)
