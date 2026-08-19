from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models import Grade
from app.services.bakalari import BakalariService


def main() -> int:
    parser = argparse.ArgumentParser(description='Synchronizace předmětů u existujících známek')
    parser.add_argument('--from-date', default='2026-01-01', help='Datum od kterého načíst známky (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Pouze zobrazit změny, nic nezapisovat')
    args = parser.parse_args()

    try:
        from_date = date.fromisoformat(args.from_date)
    except ValueError:
        print('Neplatný formát --from-date, očekává se YYYY-MM-DD', file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        fetched = BakalariService().fetch_grades(from_date)
        api_by_id = {}
        duplicate_ids = []
        for item in fetched:
            external_id = str(item['external_id'])
            if external_id in api_by_id:
                duplicate_ids.append(external_id)
            api_by_id[external_id] = item

        if duplicate_ids:
            print(f'Chyba: API vrátilo duplicitní external_id: {len(set(duplicate_ids))}', file=sys.stderr)
            return 1

        existing = {str(grade.external_id): grade for grade in db.query(Grade).all()}
        missing = sorted(set(api_by_id) - set(existing))
        changes = []

        for external_id, item in api_by_id.items():
            grade = existing.get(external_id)
            if grade is None:
                continue
            new_subject = item['subject']
            new_description = item.get('description')
            if grade.subject != new_subject or grade.description != new_description:
                changes.append((grade, new_subject, new_description))

        print(f'Známek z API: {len(fetched)}')
        print(f'Existujících známek: {len(existing)}')
        print(f'Spárováno podle external_id: {len(api_by_id) - len(missing)}')
        print(f'Nenalezeno v databázi: {len(missing)}')
        print(f'Ke změně: {len(changes)}')

        for grade, new_subject, new_description in changes:
            print(
                f'Grade {grade.id}: {grade.subject!r} -> {new_subject!r}; '
                f'description: {grade.description!r} -> {new_description!r}'
            )

        if args.dry_run:
            print('DRY-RUN: databáze nebyla změněna')
            return 0

        for grade, new_subject, new_description in changes:
            grade.subject = new_subject
            grade.description = new_description
        db.commit()
        print(f'Zapsáno změn: {len(changes)}')
        return 0
    except Exception as exc:
        db.rollback()
        print(f'Migrace selhala, provedeno rollback: {exc}', file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == '__main__':
    raise SystemExit(main())
