"""pydantic schemas for the register API wire contract.

Source of truth for what /api/v1/register accepts and what the
legacy /api/register compat shim maps onto. Empty in this commit —
Phase 5 of the v0.5.0 cleanup release introduces pydantic v2 and
populates this module. The README and PRD describe what the
schemas will enforce.
"""
