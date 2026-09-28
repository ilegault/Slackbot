import re
with open('.scratch/purchase-path-and-epif/issues/42-switch-workday-to-epif.md', 'r') as f:
    content = f.read()

content = content.replace("Status: ready-for-agent", "Status: done")
content = content.replace("- [ ]", "- [x]")
content = content.replace("## Comments", "## Comments\n\n2026-09-22: Added Switch to EPIF button in build_request_blocks. Created req_switch_epif modal workflow handling form edits securely, tracking changes correctly via Queue worker. Built robust tests verifying UI, state, role-authorization, race condition mitigation, and artifact logging properly per ADR specs.\n")

with open('.scratch/purchase-path-and-epif/issues/42-switch-workday-to-epif.md', 'w') as f:
    f.write(content)
