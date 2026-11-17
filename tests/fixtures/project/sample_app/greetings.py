from .names import normalize_name


def greet(name: str) -> str:
    return f"Hello, {normalize_name(name)}!"
