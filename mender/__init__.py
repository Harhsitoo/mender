"""Mender — a self-healing repo agent.

Mender watches a repository, and when a test breaks it diagnoses the failure,
hands the problem to Codex to write a fix, then *independently* verifies that
fix before proposing it as a pull request.

The division of labour is deliberate: Codex owns the fix, Mender owns the
trust. Mender never takes Codex's word that a patch worked.
"""

__version__ = "0.1.0"
