# 45: EPIF-path approval generates and archives the filled EPIF

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 37, 38, 44

Spec: Implementation Decision 2 (fill at approval, template source). Binding: ADR 0007
decisions 6–7, invariant 2.

**What to build:** When a request on the EPIF path is approved, the same queued write
that appends the row also fills the template and archives it under the naming rule. If
the template is missing, nothing is written.

- [x] `config.EPIF_TEMPLATE_PATH` defaults to `os.path.join(config.TEMPLATE_DIR, "EPIF_TEMPLATE_HIRST.pdf")` and can be overridden by an `EPIF_TEMPLATE_PATH` env var, like `EPIFS_DIR` in `src/config.py`. `path_validator.check_storage_paths` reports it as a **file**; add a case beside the others in `tests/test_24_startup_storage_check.py`.
- [x] In `lifecycle.finalize_purchase_request.write_action`, when `interview.get_request_route(parsed, has_file=bool(pdf_bytes))` is `epif` and no EPIF was uploaded, read the template, call `epif_filler.fill_epif`, and save with `log_writer.save_epif` under `log_writer.epif_archive_name(...)`. It runs at approval only, never at interview submit.
- [x] **All or nothing.** If the template is missing or `fill_epif` raises, the row is blanked and the error re-raised, exactly as the existing `save_bom` failure path in that same `write_action` does. Proof, modelled on `test_save_bom_raises_leaves_row_blank_no_file_card_not_advanced` in `tests/test_29_approval_archives_bom.py`: point `EPIF_TEMPLATE_PATH` at a missing file, approve, and assert the row is blank, no file is in `EPIFS_DIR`, the card was not advanced, and a failure line went to the thread.
- [x] **Scenario**: an interview request with `route = epif` is approved; one row is written and exactly one PDF exists in `EPIFS_DIR` under the naming rule, and `epif_parser.parse_epif` on that file reads back the request's vendor and amount. A Workday-path approval in the same test file adds no file.
- [x] Full gate green, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

**Tests may fake:** the Slack client (a `MagicMock` that records calls) and the network. **Tests must use real:** the handlers, `log_writer`, and a temporary copy of the workbook (copy the `temp_workbook` and `sync_queue` fixtures from `tests/test_29_approval_archives_bom.py`). A test that patches out the function this ticket changes does not count. Point `config.EPIFS_DIR` at `tmp_path` and `config.EPIF_TEMPLATE_PATH` at `tests/fixtures/EPIF_TEMPLATE_HIRST.pdf`.

## Comments

2026-09-25: Built and verified saving EPIF dynamically from template bytes on approval for EPIF route requests without uploaded files. Added comprehensive test coverage in `tests/test_45_epif_approval_archives.py` to cover success, Workday routing omission, and failure reversion (blanking row on template IO error). Updated test suites in `tests/test_30_buyers_dm_carries_bom.py` and `tests/test_24_startup_storage_check.py` to correctly supply dummy templates to fix test suite execution. Cleaned repo staging to prevent artifacts from being persisted.
