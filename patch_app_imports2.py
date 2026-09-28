with open('src/app.py', 'r') as f:
    content = f.read()

# Make sure log_writer is imported at the top
if 'import log_writer' not in content:
    content = content.replace('from . import admin, blocks, bom, config, interview, lifecycle, ops, roster, slack_io, text_rules, queue_worker',
                              'from . import admin, blocks, bom, config, interview, lifecycle, ops, roster, slack_io, text_rules, queue_worker, log_writer')

if 'from . import ' in content and 'log_writer' not in content[:3000]:
     content = content.replace('import json', 'import json\nfrom . import log_writer')

with open('src/app.py', 'w') as f:
    f.write(content)
