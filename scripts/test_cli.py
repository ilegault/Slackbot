"""CLI test tool to verify how the bot processes any EPIF PDF locally.

Usage:
    python scripts/test_cli.py samples/Prusa_EPIF__2799_PG000025831.pdf
    python test_cli.py path/to/your/epif.pdf --requester Isaac --write
    python test_cli.py --confirm-row 17
    python test_cli.py --deliver-row 17 --requester Isaac
"""
import argparse
from datetime import date
import json
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure project root and src/ are in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from src import app, config, epif_parser, log_writer, validators
except ImportError:
    import app
    import config
    import epif_parser
    import log_writer
    import validators


def main():
    parser = argparse.ArgumentParser(description="Test EPIF parsing, validation, and row generation.")
    parser.add_argument("pdf_path", nargs="?", default=None, help="Path to the EPIF PDF file")
    parser.add_argument("--requester", default="Isaac", help="Requester name (default: 'Isaac')")
    parser.add_argument("--write", action="store_true", help="Actually write the row to Purchasing-Log.xlsx and save EPIF (otherwise dry run)")
    parser.add_argument("--confirm-row", type=int, default=None, help="Mark an existing row as Confirmed")
    parser.add_argument("--deliver-row", type=int, default=None, help="Mark an existing row as Delivered")

    args = parser.parse_args()

    if args.confirm_row:
        today = date.today()
        print(f"\nMarking Row {args.confirm_row} as Confirmed (Date: {today})...")
        try:
            log_writer.update_row(args.confirm_row, {config.COLUMN_DATE_CONFIRMED: today})
            info = log_writer.get_row_info(args.confirm_row)
            print(f"SUCCESS: Row {args.confirm_row} for '{info.get('item_description')}' is now Confirmed.")
        except Exception as e:
            print(f"FAILED: {e}")
        return

    if args.deliver-row if hasattr(args, "deliver_row") else False:
        pass

    if args.deliver_row:
        today = date.today()
        print(f"\nMarking Row {args.deliver_row} as Delivered (Date: {today}, Received By: {args.requester})...")
        try:
            log_writer.update_row(args.deliver_row, {
                config.COLUMN_DATE_DELIVERY: today,
                config.COLUMN_RECEIVED_BY: args.requester,
            })
            info = log_writer.get_row_info(args.deliver_row)
            print(f"SUCCESS: Row {args.deliver_row} for '{info.get('item_description')}' is now Delivered.")
        except Exception as e:
            print(f"FAILED: {e}")
        return

    if not args.pdf_path:
        parser.print_help()
        sys.exit(1)

    # Allow relative path from current working directory or samples dir
    pdf_path = args.pdf_path
    if not os.path.exists(pdf_path):
        sample_path = os.path.join(PROJECT_ROOT, "samples", os.path.basename(pdf_path))
        if os.path.exists(sample_path):
            pdf_path = sample_path
        else:
            print(f"Error: File not found: {args.pdf_path}")
            sys.exit(1)

    print(f"\n=======================================================")
    print(f"  Testing EPIF Bot Processing for: {os.path.basename(pdf_path)}")
    print(f"=======================================================\n")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    # 1. Parse
    try:
        parsed = epif_parser.parse_epif(pdf_bytes)
        print("[1] AcroForm Parsing: SUCCESS")
        print(f"    - Item:        {parsed['item_description']}")
        print(f"    - Vendor:      {parsed['vendor']} ({parsed['vendor_contact_email']})")
        print(f"    - Amount:      ${parsed['total_price']}")
        print(f"    - Date:        {parsed['date_of_purchase']}")
        print(f"    - Project ID:  {parsed['project_id']}")
        print(f"    - Fund:        {parsed['fund']}")
        print(f"    - Category:    {parsed['category']}")
        print(f"    - Payment:     {parsed['payment_method']}")
        print(f"    - Link:        {parsed['link']}")
    except epif_parser.FlattenedPdfError as e:
        print(f"[1] AcroForm Parsing: FAILED (Flattened PDF)\n    {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[1] AcroForm Parsing: ERROR: {e}")
        sys.exit(1)

    # 2. Validate
    print("\n[2] Validation:")
    problems = validators.validate(parsed, requester_name=args.requester)
    if problems:
        print(f"    REJECTED with {len(problems)} problem(s):")
        for p in problems:
            print(f"      • {p}")
    else:
        print("    PASSED - Form is valid and safe to log!")

    # 3. Row Representation & Email Draft
    row_dict = log_writer.build_row(parsed, args.requester)
    print("\n[3] Generated OrderLog Row Columns:")
    for col, val in sorted(row_dict.items()):
        print(f"    Col {col}: {val}")

    print("\n[3b] Generated Email Draft for Requester:")
    email_draft = app.generate_email_draft(parsed, args.requester)
    print("-------------------------------------------------------")
    print(email_draft)
    print("-------------------------------------------------------")

    # 4. Write
    if args.write:
        if problems:
            print("\n[!] Skipping write because validation failed.")
        else:
            print(f"\n[4] Writing to workbook: {config.WORKBOOK_PATH}")
            try:
                row_num = log_writer.append_row(row_dict)
                print(f"    SUCCESS: Written to row {row_num}!")
                saved_epif = log_writer.save_epif(pdf_bytes, os.path.basename(pdf_path))
                print(f"    SUCCESS: Saved EPIF to {saved_epif}!")
            except Exception as e:
                print(f"    FAILED to write: {e}")
    else:
        print("\n[4] Dry run completed (use --write to append to workbook and save EPIF).")


if __name__ == "__main__":
    main()
