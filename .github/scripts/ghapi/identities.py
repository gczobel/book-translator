"""Numeric GitHub account IDs the automation trusts (ADR 0005, invariant 2).

Identity is the ID, never the login. One copy, so no package can drift from the others.
"""

OWNER_ID = 754466  # gczobel
DEPENDABOT_ID = 49699333  # dependabot[bot]
MAINT_BOT_ID = 361970745  # book-translator-maint[bot], App ID 5952645
AGENT_BOT_ID = 361973881  # the Agent App's bot user (App ID 5952762); never matched by login
