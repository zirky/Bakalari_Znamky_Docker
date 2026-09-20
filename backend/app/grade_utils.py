from typing import Optional


def absolute_grade_value(value: object) -> Optional[str]:
    """
    Převede školní známku na základní hodnotu pro odměny a průměry.

    1+, 1, 1- -> "1"
    2+, 2, 2- -> "2"
    3+, 3, 3- -> "3"
    4+, 4, 4- -> "4"
    5+, 5, 5- -> "5"

    Nečíselné hodnocení vrací None.
    """
    normalized = str(value or '').strip().replace(' ', '')

    if normalized in {'1', '2', '3', '4', '5'}:
        return normalized

    if (
        len(normalized) == 2
        and normalized[0] in {'1', '2', '3', '4', '5'}
        and normalized[1] in {'+', '-'}
    ):
        return normalized[0]

    return None
