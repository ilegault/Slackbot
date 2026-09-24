import re

with open("tests/test_onboarding_and_commands.py", "r") as f:
    content = f.read()

content = content.replace(
    'assert "Needs a Grad Student Buyer to process in Workday / ShopUW." in broadcast_text',
    'assert "Needs a buyer to email to purchasing." in broadcast_text'
)

with open("tests/test_onboarding_and_commands.py", "w") as f:
    f.write(content)
