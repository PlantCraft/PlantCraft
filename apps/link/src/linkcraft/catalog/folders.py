"""Folders the site makes for its blocks, algorithms and schedules (owner D14, 2026-10-26).

The store is the platform's (``plantcraft_sdk.server.folders``): ``folders`` and
``folder_items``, who moved what and when. The block libraries Link ships stay fixed: only the
site's own blocks go in folders. An execution sits in its schedule's folder. Folders are not the
user group that edits an algorithm (``method_profiles.group_id``): that one says who, this one
says where.
"""

from __future__ import annotations

from plantcraft_sdk.server.folders import FolderStore as _FolderStore

KINDS = ("block", "algorithm", "schedule")


class FolderStore(_FolderStore):
    KINDS = KINDS


__all__ = ["KINDS", "FolderStore"]
