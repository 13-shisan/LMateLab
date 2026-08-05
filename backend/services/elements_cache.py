# services/elements_cache.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import time
from typing import Dict, List, Optional, Tuple

@dataclass
class CacheItem:
    mtime: float
    elements: List[str]
    updated_at: float

_lock = Lock()
_cache: Dict[str, CacheItem] = {}

def get_cached(dbpath: Path) -> Optional[List[str]]:
    key = str(dbpath)
    mtime = dbpath.stat().st_mtime
    with _lock:
        item = _cache.get(key)
        if item and item.mtime == mtime:
            return item.elements
    return None

def set_cached(dbpath: Path, elements: List[str]) -> None:
    key = str(dbpath)
    mtime = dbpath.stat().st_mtime
    with _lock:
        _cache[key] = CacheItem(mtime=mtime, elements=elements, updated_at=time())
