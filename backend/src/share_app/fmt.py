"""Human-readable sizes and plurals in English and Russian — for logs and OG tags."""

from __future__ import annotations

UNITS = {
    "en": ("B", ("KB", "MB", "GB", "TB"), "."),
    "ru": ("Б", ("КБ", "МБ", "ГБ", "ТБ"), ","),
}


def human_size(n: int, lang: str = "en") -> str:
    byte, units, point = UNITS[lang]
    if n < 1024:
        return f"{n} {byte}"
    value = float(n)
    for unit in units:
        value /= 1024
        if value < 1023.5 or unit == units[-1]:  # otherwise 1023.6 MB would round to "1024 MB"
            text = f"{value:.1f}" if value < 100 else f"{value:.0f}"
            return f"{text.removesuffix('.0').replace('.', point)} {unit}"
    raise AssertionError("unreachable")


def plural(n: int, lang: str, forms: tuple[str, ...]) -> str:
    """Plural form: `forms` is (one, other) for English and (one, few, many) for Russian."""
    if lang == "en":
        return forms[0] if n == 1 else forms[1]
    one, few, many = forms
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many
