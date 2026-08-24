from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any

import httpx

from ..config import get_settings


class BakalariError(RuntimeError):
    """Raised when the Bakalari API cannot be used."""


class BakalariService:
    API_PREFIXES = ('', '/bakalari', '/bakaweb', '/webrodice', '/dm', '/mobile')

    def __init__(self, timeout: float = 15.0):
        self.settings = get_settings()
        self.timeout = timeout
        self.base_url = self.settings.bakalari_base_url.rstrip('/')
        self.username = self.settings.bakalari_username
        self.password = self.settings.bakalari_password
        configured_prefix = getattr(self.settings, 'bakalari_api_prefix', None)
        self.api_prefix = configured_prefix.strip().strip('/') if configured_prefix else None

    def _api_url(self, prefix: str, path: str) -> str:
        prefix = f'/{prefix.strip("/")}' if prefix.strip('/') else ''
        return f'{self.base_url}{prefix}/api/{path.lstrip("/")}'

    def _login(self, client: httpx.Client, prefix: str) -> str:
        response = client.post(
            self._api_url(prefix, 'login'),
            data={
                'client_id': 'ANDR',
                'grant_type': 'password',
                'username': self.username,
                'password': self.password,
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise BakalariError('Bakalari login vrátil neplatný JSON') from exc
        token = payload.get('access_token')
        if not token:
            raise BakalariError('Bakalari login nevrátil access_token')
        return str(token)

    def _authenticate(self, client: httpx.Client) -> tuple[str, str]:
        if not self.base_url or not self.username or not self.password:
            raise BakalariError('Bakalari API není nakonfigurováno')
        prefixes = (self.api_prefix,) if self.api_prefix is not None else self.API_PREFIXES
        last_error: Exception | None = None
        for prefix in prefixes:
            try:
                return prefix, self._login(client, prefix)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code == 404:
                    continue
                if exc.response.status_code in (400, 401, 403):
                    raise BakalariError('Přihlášení k Bakářům selhalo') from exc
                raise BakalariError(f'Bakalari login selhal HTTP {exc.response.status_code}') from exc
            except (httpx.HTTPError, BakalariError) as exc:
                last_error = exc
                if isinstance(exc, BakalariError):
                    raise
        raise BakalariError('API endpoint Bakalářů nebyl nalezen') from last_error

    def fetch_grades(self, from_date: date | None = None) -> list[dict[str, Any]]:
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                prefix, token = self._authenticate(client)
                response = client.get(
                    self._api_url(prefix, '3/marks'),
                    headers={'Authorization': f'Bearer {token}'},
                )
                response.raise_for_status()
                payload = response.json()
        except BakalariError:
            raise
        except httpx.HTTPStatusError as exc:
            raise BakalariError(f'Načtení známek selhalo HTTP {exc.response.status_code}') from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise BakalariError(f'Načtení známek z Bakalářů selhalo: {exc}') from exc

        result: list[dict[str, Any]] = []
        subjects = payload.get('Subjects', []) if isinstance(payload, dict) else []
        if not isinstance(subjects, list):
            raise BakalariError('Bakalari API vrátilo neočekávaný formát známek')

        for subject in subjects:
            if not isinstance(subject, dict):
                continue
            subject_value = subject.get('Subject')
            if isinstance(subject_value, dict):
                subject_name = (
                    subject_value.get('Name')
                    or subject_value.get('Caption')
                    or subject_value.get('Abbrev')
                    or 'Neznámý předmět'
                )
            else:
                subject_name = (
                    subject_value
                    or subject.get('Caption')
                    or subject.get('Name')
                    or subject.get('SubjectName')
                    or 'Neznámý předmět'
                )
            marks = subject.get('Marks', [])
            if not isinstance(marks, list):
                continue
            for mark in marks:
                normalized = self._normalize_mark(mark, str(subject_name))
                if normalized and (from_date is None or normalized['grade_date'] >= from_date):
                    result.append(normalized)
        return result

    def get_timetable(self) -> list[dict[str, Any]]:
        """
        Získá rozvrh hodin z Bakalářů API.
        
        Vrátí seznam ve tvaru:
        [
            {
                "day_of_week": 1,  # 1=pondělí .. 7=neděle
                "lesson_number": 1,  # pořadí hodiny
                "subject": "Matematika",
                "room": "A12",
                "teacher": "Novák",
                "note": "",
                "valid_from": "2026-09-01",  # nebo None
                "valid_to": "2027-06-30"  # nebo None
            },
            ...
        ]
        """
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                prefix, token = self._authenticate(client)
                response = client.get(
                    self._api_url(prefix, '3/timetable/actual'),
                    headers={'Authorization': f'Bearer {token}'},
                )
                response.raise_for_status()
                payload = response.json()
        except BakalariError:
            raise
        except httpx.HTTPStatusError as exc:
            raise BakalariError(f'Načtení rozvrhu selhalo HTTP {exc.response.status_code}') from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise BakalariError(f'Načtení rozvrhu z Bakalářů selhalo: {exc}') from exc

        result: list[dict[str, Any]] = []
        
        # Bakaláři API vrací rozvrh jako seznam dní (Monday..Sunday)
        days = payload if isinstance(payload, list) else []
        
        for day_index, day_data in enumerate(days, start=1):
            if not isinstance(day_data, dict):
                continue
            
            # Získání hodin pro daný den
            lessons = day_data.get('Lessons', [])
            if not isinstance(lessons, list):
                continue
            
            for lesson in lessons:
                if not isinstance(lesson, dict):
                    continue
                
                normalized = self._normalize_lesson(lesson, day_index)
                if normalized:
                    result.append(normalized)
        
        return result

    def _normalize_lesson(
        self, lesson: dict[str, Any], day_of_week: int
    ) -> dict[str, Any] | None:
        """
        Normalizuje jednu hodinu z Bakalářů API.
        """
        if not isinstance(lesson, dict):
            return None
        
        # Získání předmětu
        subject_data = lesson.get('Subject', {})
        if isinstance(subject_data, dict):
            subject = (
                subject_data.get('Name')
                or subject_data.get('Caption')
                or subject_data.get('Abbrev')
                or 'Neznámý předmět'
            )
        else:
            subject = str(subject_data or 'Neznámý předmět')
        
        # Získání učebny
        room_data = lesson.get('Room', {})
        if isinstance(room_data, dict):
            room = room_data.get('Name') or room_data.get('Caption') or None
        else:
            room = str(room_data) if room_data else None
        
        # Získání učitele
        teacher_data = lesson.get('Teacher', {})
        if isinstance(teacher_data, dict):
            teacher = (
                teacher_data.get('Name')
                or teacher_data.get('Caption')
                or None
            )
        else:
            teacher = str(teacher_data) if teacher_data else None
        
        # Získání poznámky
        note = lesson.get('Note') or lesson.get('Comment') or lesson.get('Description')
        
        # Získání čísla hodiny
        lesson_number = lesson.get('LessonNumber') or lesson.get('Order') or 0
        
        # Získání data platnosti
        valid_from = None
        valid_to = None
        
        start_date = lesson.get('StartDate') or lesson.get('ValidFrom')
        if start_date:
            try:
                valid_from = self._parse_date(str(start_date)).isoformat()
            except ValueError:
                pass
        
        end_date = lesson.get('EndDate') or lesson.get('ValidTo')
        if end_date:
            try:
                valid_to = self._parse_date(str(end_date)).isoformat()
            except ValueError:
                pass
        
        return {
            'day_of_week': day_of_week,
            'lesson_number': int(lesson_number),
            'subject': str(subject).strip(),
            'room': str(room).strip() if room else None,
            'teacher': str(teacher).strip() if teacher else None,
            'note': str(note).strip() if note else None,
            'valid_from': valid_from,
            'valid_to': valid_to,
        }

    def _normalize_mark(
        self, mark: dict[str, Any], subject: str
    ) -> dict[str, Any] | None:
        if not isinstance(mark, dict):
            return None
        raw_date = mark.get('MarkDate') or mark.get('Date')
        value = mark.get('MarkText') or mark.get('Value') or mark.get('Grade')
        if not raw_date or value is None:
            return None
        try:
            grade_date = self._parse_date(str(raw_date))
        except ValueError:
            return None

        description = (
            mark.get('Caption')
            or mark.get('Theme')
            or mark.get('Description')
            or mark.get('Note')
            or mark.get('Comment')
        )
        external_id = mark.get('Id') or mark.get('ID') or mark.get('MarkId')
        if not external_id:
            identity = '|'.join(
                (
                    self.base_url,
                    subject.strip(),
                    str(value).strip(),
                    grade_date.isoformat(),
                    str(description or ''),
                )
            )
            external_id = hashlib.sha256(identity.encode('utf-8')).hexdigest()
        return {
            'external_id': str(external_id),
            'subject': subject.strip(),
            'grade_value': str(value).strip(),
            'grade_date': grade_date,
            'description': str(description).strip() if description else None,
            'source': 'bakalari',
        }

    @staticmethod
    def _parse_date(value: str) -> date:
        candidate = value.strip().replace('Z', '+00:00')
        try:
            return datetime.fromisoformat(candidate).date()
        except ValueError:
            for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y'):
                try:
                    return datetime.strptime(value.strip(), fmt).date()
                except ValueError:
                    continue
        raise ValueError(f'Neplatné datum známky: {value}')
