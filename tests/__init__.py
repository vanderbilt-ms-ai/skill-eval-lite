import os

# The tests never ask GitHub for the latest version (doctor and status do);
# tests/test_status.py points it at a file instead.
os.environ["SKILL_EVAL_LITE_UPDATE_URL"] = "off"
