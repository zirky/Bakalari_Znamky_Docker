from datetime import date

SCHOOL_YEAR_START_MONTH = 9
SCHOOL_YEAR_START_DAY = 1


def school_year_for_date(value: date) -> str:
    start_year = value.year
    if (value.month, value.day) < (SCHOOL_YEAR_START_MONTH, SCHOOL_YEAR_START_DAY):
        start_year -= 1
    return f"{start_year}/{start_year + 1}"


def current_school_year(today: date | None = None) -> str:
    return school_year_for_date(today or date.today())
