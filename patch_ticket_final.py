with open('.scratch/purchase-path-and-epif/issues/42-switch-workday-to-epif.md', 'r') as f:
    content = f.read()

content = content.replace("**Status:** ready-for-agent", "**Status:** done")

with open('.scratch/purchase-path-and-epif/issues/42-switch-workday-to-epif.md', 'w') as f:
    f.write(content)
