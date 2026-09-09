#!/usr/bin/env python3
"""Main entry point for P-Bot (Hirst Lab Purchasing Bot)."""
import os
import sys

# Ensure project root and src/ are in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(BASE_DIR, "src")
for p in (BASE_DIR, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.app import main, app, generate_email_draft

if __name__ == "__main__":
    main()
