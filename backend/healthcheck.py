import os
from urllib.error import HTTPError
from urllib.request import urlopen


BASE_URL = os.getenv("HEALTHCHECK_BASE_URL", "http://127.0.0.1:4000").rstrip("/")


def probe(path: str) -> None:
    with urlopen(f"{BASE_URL}{path}", timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"health probe returned HTTP {response.status}")


def main() -> None:
    try:
        probe("/api/health/ready")
    except HTTPError as error:
        if error.code != 404:
            raise
        probe("/api/academic-reports?page=1&page_size=1")


if __name__ == "__main__":
    main()
