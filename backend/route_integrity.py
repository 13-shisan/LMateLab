from collections import defaultdict


IGNORED_METHODS = {"HEAD", "OPTIONS"}


def duplicate_routes(app):
    registrations = defaultdict(list)

    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path:
            continue

        for method in methods:
            method = method.upper()
            if method in IGNORED_METHODS:
                continue
            registrations[(method, path)].append(
                getattr(route, "name", "<unnamed>")
            )

    return {
        key: names
        for key, names in registrations.items()
        if len(names) > 1
    }


def assert_unique_routes(app):
    duplicates = duplicate_routes(app)
    if not duplicates:
        return

    details = "; ".join(
        f"{method} {path}: {', '.join(names)}"
        for (method, path), names in sorted(duplicates.items())
    )
    raise RuntimeError(f"duplicate FastAPI routes: {details}")
