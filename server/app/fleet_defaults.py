"""Стандартные имена новых флотов (до переименования игроком)."""

DEFAULT_FLEET_DISPLAY_NAMES: tuple[str, ...] = (
    "Alpha (Альфа)",
    "Beta (Бета)",
    "Gamma (Гамма)",
    "Delta (Дельта)",
    "Epsilon (Эпсилон)",
    "Zeta (Дзета)",
    "Eta (Эта)",
    "Theta (Тета)",
    "Iota (Йота)",
    "Kappa (Каппа)",
)


def fleet_display_name_for_index(index: int) -> str:
    if index >= 0 and index < len(DEFAULT_FLEET_DISPLAY_NAMES):
        return DEFAULT_FLEET_DISPLAY_NAMES[index]
    return f"Флот {index + 1}"
