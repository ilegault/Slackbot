import re

with open('tests/test_42_switch_workday_to_epif.py', 'r') as f:
    content = f.read()

# Fix the column A issue
search_str = 'log_writer.update_row(15, {"A": "15", "B": "Vendor", "C": "Item"}, workbook_path=temp_workbook)'
replace_str = 'log_writer.update_row(15, {"B": "Vendor", "C": "Item"}, workbook_path=temp_workbook)'
content = content.replace(search_str, replace_str)

search_str2 = 'log_writer.update_row(15, {"A": "15", config.COLUMN_REQUESTER: "Original Requester", "C": "Old Item", config.COLUMN_DATE_OF_REQUEST: "2026-09-20"}, workbook_path=temp_workbook)'
replace_str2 = 'log_writer.update_row(15, {config.COLUMN_REQUESTER: "Original Requester", "C": "Old Item", config.COLUMN_DATE_OF_REQUEST: "2026-09-20"}, workbook_path=temp_workbook)'
content = content.replace(search_str2, replace_str2)

with open('tests/test_42_switch_workday_to_epif.py', 'w') as f:
    f.write(content)
