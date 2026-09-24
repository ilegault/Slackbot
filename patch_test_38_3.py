import re

with open("tests/test_38_workday_path_approval.py", "r") as f:
    content = f.read()

content = content.replace(
    'monkeypatch.setattr(lifecycle.log_writer, "append_row", lambda vals, workbook_path=None: 21)',
    'monkeypatch.setattr(lifecycle.log_writer, "append_row", lambda vals, workbook_path=None: 21)\n    monkeypatch.setattr(lifecycle.log_writer, "get_row_info", lambda row: {"row": row})'
)
content = content.replace(
    'row_info = log_writer.get_row_info(row) if row else {}',
    'row_info = {"row": row}'
)

with open("tests/test_38_workday_path_approval.py", "w") as f:
    f.write(content)
