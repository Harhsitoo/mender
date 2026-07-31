"""Delivery — turning a verified fix into something a human can review."""

from mender.deliver.pr import deliver, render_pr_body

__all__ = ["deliver", "render_pr_body"]
