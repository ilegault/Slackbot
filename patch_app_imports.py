with open('src/app.py', 'r') as f:
    content = f.read()

# Add log_writer import if missing. `app.py` doesn't import log_writer, it might need it.
if 'from . import ' in content and 'log_writer' not in content[:1000]:
    content = content.replace('from . import admin, blocks, bom, config, interview, lifecycle, ops, roster, slack_io, text_rules, queue_worker',
                              'from . import admin, blocks, bom, config, interview, lifecycle, ops, roster, slack_io, text_rules, queue_worker, log_writer')

# Remove unused variable updated_columns
import re
content = re.sub(r'updated_columns = log_writer\.request_to_row_values\([^)]+\)', '', content, flags=re.MULTILINE|re.DOTALL)

with open('src/app.py', 'w') as f:
    f.write(content)
