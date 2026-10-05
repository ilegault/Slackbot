# 84: Cancel moves quotes out

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 83

**Spec:** `.scratch/attached-boms-and-quotes/spec.md`
**Binding:** `docs/adr/0012-attached-boms-and-quotes-are-carried-not-read.md` decision 5; `docs/adr/0006-bom-line-items-and-editable-posted-cards.md` decision 7; ADR 0001

## What to build

Cancelling an approved request moves its archived quotes into `QUOTES_DIR/Cancelled/`, the same
way the BOM already moves into `BOMS_DIR/Cancelled/`, so the live folder matches the live log and a
recycled row number can't collide with old quotes.

1. `src/lifecycle.py`: new `_move_quotes_to_cancelled(names: list[str]) -> None`, a copy of
   `_move_bom_to_cancelled` for `config.QUOTES_DIR`: a missing file logs a warning and is skipped.
2. `src/lifecycle.py` `handle_cancel`: beside the existing `bom_file` move, when
   `req_data.get("quote_count")` is a positive int, build the names with
   `bom.quote_filename(row, vendor, k)` for k = 1…count (row and vendor from the same place the
   cancel already reads them) and call `_move_quotes_to_cancelled`.

An attached BOM (any extension) is already moved by the existing `bom_file` logic; this ticket
only proves that.

## Acceptance criteria

New test file `tests/test_84_cancel_moves_quotes.py`, set up like `tests/test_31_cancel_moves_bom.py`
(temp `QUOTES_DIR`, `BOMS_DIR`, temp workbook copy).

- [ ] **Quotes move.** Cancelling an approved card with `quote_count: 3` and the three files present leaves `QUOTES_DIR` with no `_Quote_` files and `QUOTES_DIR/Cancelled/` with all three.
- [ ] **A missing quote doesn't block the cancel.** Same with `_Quote_2.pdf` absent → quotes 1 and 3 moved, the row is blanked as in `tests/test_31_cancel_moves_bom.py`, no exception.
- [ ] **No quotes, no change.** A card without `quote_count` cancels exactly as before; `QUOTES_DIR/Cancelled/` is not created.
- [ ] **Attached CSV BOM moves.** A card with `bom_file` `<row>_<Vendor>_BOM.csv` → that file ends up in `BOMS_DIR/Cancelled/`.

**Tests may fake:** the Slack client. **Must be real:** `handle_cancel`, the file moves in the temp folders, `bom.quote_filename`.

## Gate

Run in this order, exactly as CI does (`.github/workflows/tests.yml`). Zero failures before
you push.

```
ruff check .
python scripts/check_tests_first.py
python tools/type_gate.py
pytest --tb=short -q -n auto --dist loadfile
```

## Comments
