"""Base scraper protocol.

Each scraper fetches from one source kind and returns a list of ContentItems
published at-or-after the given cutoff. Scrapers do not touch the database.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime

import httpx

from ..models import ContentItem


def item_id_for(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


class Scraper(ABC):
    name: str

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    @abstractmethod
    async def fetch(self, since: datetime) -> list[ContentItem]:
        ...
