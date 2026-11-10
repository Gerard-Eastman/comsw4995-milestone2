"""Regression suite runner: base, roles (A) and channels (B) rules."""
import os, sys
os.environ["REGRESSION"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa
import base_checks, roles_checks, channels_checks  # noqa: registers the rules
lib.run(["regression", "all"], budget=24)
