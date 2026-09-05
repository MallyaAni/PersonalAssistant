"""The security agent: a read-only investigation of one commit, run durably.

Its first shape is the reviewer's shape with a different question - not "is
this change correct" but "does this change widen what an attacker can do" -
plus deterministic greps for secret-shaped and dangerous-call lines that the
model then judges. The authorized scope is the repository the read-only repo
server is rooted at; anything else is refused before a tool is called. See
docs/AGENT_CATALOG.md, "Adding an agent".
"""
