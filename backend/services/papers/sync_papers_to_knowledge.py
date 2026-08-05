# backend/services/papers/sync_papers_to_knowledge.py
import os
import shutil

from .config import KNOWLEDGE_RAW_PAPERS_DIR, PAPERS_LIBRARY_DIR
from .utils import ensure_dir


def _same_file_fast(src: str, dst: str) -> bool:
    if not os.path.exists(dst):
        return False
    try:
        return (
            os.path.getsize(src) == os.path.getsize(dst)
            and int(os.path.getmtime(src)) == int(os.path.getmtime(dst))
        )
    except Exception:
        return False


def sync_papers_to_knowledge(clean_deleted: bool = True) -> dict:
    copied = 0
    removed = 0

    print(f"[sync_papers] PAPERS_LIBRARY_DIR={PAPERS_LIBRARY_DIR}", flush=True)
    print(f"[sync_papers] KNOWLEDGE_RAW_PAPERS_DIR={KNOWLEDGE_RAW_PAPERS_DIR}", flush=True)

    ensure_dir(KNOWLEDGE_RAW_PAPERS_DIR)
    
    if not os.path.isdir(PAPERS_LIBRARY_DIR):
        raise FileNotFoundError(f"PAPERS_LIBRARY_DIR not found: {PAPERS_LIBRARY_DIR}")


    source_files = set()
    target_files = set()

    for root, dirs, files in os.walk(PAPERS_LIBRARY_DIR):
        dirs[:] = [d for d in dirs if d != "mineru"]

        for name in files:
            if name != "full.md":
                continue

            src = os.path.join(root, name)
            rel = os.path.relpath(src, PAPERS_LIBRARY_DIR)
            dst = os.path.join(KNOWLEDGE_RAW_PAPERS_DIR, rel)

            source_files.add(rel)
            ensure_dir(os.path.dirname(dst))

            if not _same_file_fast(src, dst):
                shutil.copy2(src, dst)
                copied += 1
                print(f"[sync_papers] copied: {rel}", flush=True)

    print(f"[sync_papers] source_files_count={len(source_files)}", flush=True)

    if clean_deleted:
        for root, _, files in os.walk(KNOWLEDGE_RAW_PAPERS_DIR):
            for name in files:
                if not name.lower().endswith(".md"):
                    continue

                dst = os.path.join(root, name)
                rel = os.path.relpath(dst, KNOWLEDGE_RAW_PAPERS_DIR)
                target_files.add(rel)

        print(f"[sync_papers] target_files_count={len(target_files)}", flush=True)

        stale_files = target_files - source_files
        for rel in sorted(stale_files):
            stale_path = os.path.join(KNOWLEDGE_RAW_PAPERS_DIR, rel)
            if os.path.exists(stale_path):
                os.remove(stale_path)
                removed += 1
                print(f"[sync_papers] removed stale: {rel}", flush=True)

    print(f"[sync_papers] done, copied={copied}, removed={removed}", flush=True)
    return {
        "copied": copied,
        "removed": removed,
    }


def main():
    sync_papers_to_knowledge(clean_deleted=True)


if __name__ == "__main__":
    main()
