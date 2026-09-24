# 44: One naming rule for archived EPIFs, never overwriting

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

Spec: Implementation Decision 2 (naming). Binding: ADR 0007 decision 7.

**What to build:** A pure function that names an archived EPIF
`<vendor>_EPIF_$<price>_<project id>.pdf`, and a `save_epif` that never overwrites.
Tickets 39 and 45 use them.

- [x] New pure function `log_writer.epif_archive_name(vendor: str, total_price: float, project_id: str, existing: Iterable[str]) -> str`. Tests assert exact outputs: `("Winford", 17.1, "PG000025831", [])` → `Winford_EPIF_$17.10_PG000025831.pdf`; a price of 1234.5 gives `$1234.50` (no thousands separator); a vendor `Acme <Lab> Supply` gives `Acme Lab Supply_…` (characters `<>:"/\|?*` removed, whitespace runs collapsed); with the plain name already in `existing` it returns `…_2.pdf`, and with that also present, `…_3.pdf`.
- [x] `log_writer.save_epif` refuses to replace an existing file: if the destination exists it raises `FileExistsError` instead of calling `os.replace`. A test writes a file, calls `save_epif` with the same name, asserts the error, and asserts the original bytes are unchanged.
- [x] Full gate green, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

**Tests may fake:** nothing; these are pure functions plus a `tmp_path` directory.

## Comments
2025-02-15: Built `epif_archive_name` pure function to generate filename based on vendor, price, project id and existing names. Updated `save_epif` to refuse overwriting. Tests pass and all acceptance criteria met.
