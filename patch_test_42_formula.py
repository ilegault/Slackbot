import re

with open('tests/test_42_switch_workday_to_epif.py', 'r') as f:
    content = f.read()

# Replace any "A": "..." or "B": "..." writes since we learned "B" is requester.
# And test_42 output says: "Column A holds a formula and must not be written."
# wait, config.COLUMN_REQUESTER = "B", and log_writer.update_row complains about column A
# Let's replace "A" with "E" (Payment Method) or just remove "A": "15" from dict

content = content.replace('{"A": "15", "B": "Vendor", "C": "Item"}', '{"B": "Original Requester", "C": "Item"}')
content = content.replace('{"B": "Vendor", "C": "Item"}', '{"B": "Original Requester", "C": "Item"}')

with open('tests/test_42_switch_workday_to_epif.py', 'w') as f:
    f.write(content)
