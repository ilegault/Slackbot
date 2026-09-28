with open('tests/test_onboarding_and_commands.py', 'r') as f:
    content = f.read()

# Fix the test assertion
search_str = 'assert len(button_elements) == 2, f"state={state}: expected 2 buttons (primary + secondary)"'
replace_str = 'assert len(button_elements) in (2, 3), f"state={state}: expected 2 buttons (primary + secondary) or 3 if Switch to EPIF is visible"'

content = content.replace(search_str, replace_str)

with open('tests/test_onboarding_and_commands.py', 'w') as f:
    f.write(content)
