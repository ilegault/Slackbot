# 36: Commit the blank EPIF template as a test fixture

**Status:** human-task

**Blocked by:** None (can start immediately)

**What to build:** Isaac copies the blank `EPIF_TEMPLATE_HIRST.pdf` from the OneDrive
`Purchasing/_TEMPLATE` folder into the repo's test fixtures directory (`tests/fixtures/`,
creating it if needed) and commits it to `master`. It is a blank university form with no
personal data. Ticket 37's round-trip test fills this exact file. **An agent must not
claim this ticket.**

- [ ] `EPIF_TEMPLATE_HIRST.pdf` is committed under `tests/fixtures/` on `master`.
- [ ] It is the blank form: every field is empty, and it has not been flattened.

## Comments
