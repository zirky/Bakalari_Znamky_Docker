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
            raise BakalariError('Bakalari login vrÃ¡til neplatnÃ½ JSON') from exc
        token = payload.get('access_token')
        if not token:
            raise BakalariError('Bakalari login nevrÃ¡til access_token')
        return str(token)

    def _authenticate(self, client: httpx.Client) -> tuple[str, str]:
        if not self.base_url or not self.username or not self.password:
            raise BakalariError('Bakalari API nenÃ¬ nakonfigurovÃ¡no')
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
                    raise BakalariError('PÅ°ihlÃ¡Å¡enÃ¬ k BakÃ¡Å°Å¯m selhalo') from exc
                raise BakalariError(f'Bakalari login selhalo HTTP {exc.response.status_code}') from exc
            except (httpx.HTTPError, BakalariError) as exc:
                last_error = exc
                if isinstance(exc, BakalariError):
                    raise
        raise BakalariError('API endpoint BakalÃ¡Å°Å¯ nebyl nalezen') from last_error

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
            raise BakalariError(f'NaÄ�tenÃ¬ znÃ¡mek selhalo HTTP {exc.response.status_code}') from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise BakalariError(f'NaÄ�tenÃ¬ znÃ¡mek z BakalÃ¡Å°Å¯ selhalo: {exc}') from exc

        result: list[dict[str, Any]] = []
        subjects = payload.get('Subjects', []) if isinstance(payload, dict) else []
        if not isinstance(subjects, list):
            raise BakalariError('Bakalari API vrÃ¡tilo neoÄ�ekÃ¡vanÃ½ formÃ¡t znÃ¡mek')

        for subject in subjects:
            if not isinstance(subject, dict):
                continue
            subject_value = subject.get('Subject')
            if isinstance(subject_value, dict):
                subject_name = (
                    subject_value.get('Name')
                    or subject_value.get('Caption')
                    or subject_value.get('Abbrev')
                    or 'NeznÃ¡mÃ½ pÅ°edmÄºt'
                )
            else:
                subject_name = (
                    subject_value
                    or subject.get('Caption')
                    or subject.get('Name')
                    or subject.get('SubjectName')
                    or 'NeznÃ¡mÃ½ pÅ°edmÄºt'
                )
            marks = subject.get('Marks', [])
            if not isinstance(marks, list):
                continue
            for mark in marks:
                normalized = self._normalize_mark(mark, str(subject_name))
                if normalized and (from_date is None or normalized['grade_date'] >= from_date):
                    result.append(normalized)
        return result

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
        raise ValueError(f'NeplatnÃ© datum znÃ¡mky: {value}')

    def fetch_timetable(self) -> list[dict[str, Any]]:
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                prefix, token = self._authenticate(client)
                response = client.get(
                    self._api_url(prefix, '3/timetable'),
                    headers={'Authorization': f'Bearer {token}'},
                )
                response.raise_for_status()
                payload = response.json()
        except BakalariError:
            raise
        except httpx.HTTPStatusError as exc:
            raise BakalariError(f'NaÄ�tenÃ¬ rozvrhu selhalo HTTP {exc.response.status_code}') from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise BakalariError(f'NaÄ�tenÃ¬ rozvrhu z BakalÃ¡Å°Å¯ selhalo: {exc}') from exc

        result: list[dict[str, Any]] = []
        
        days = payload.get('Days', []) if isinstance(payload, dict) else []
        if not isinstance(days, list):
            raise BakalariError('Bakalari API vrÃ¡tilo neoÄ�ekÃ¡vanÃ½ formÃ¡t rozvrhu')

        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        
        for day_index, day_data in enumerate(days):
            if not isinstance(day_data, dict):
                continue
            
            day_name = day_data.get('Name', '')
            if day_name not in day_names:
                continue
            
            hours = day_data.get('Hours', [])
            if not isinstance(hours, list):
                continue
            
            for hour_data in hours:
                if not isinstance(hour_data, dict):
                    continue
                
                normalized = self._normalize_timetable_entry(hour_data, day_index)
                if normalized:
                    result.append(normalized)
        
        return result

    def _normalize_timetable_entry(
        self, hour_data: dict[str, Any], day_index: int
    ) -> dict[str, Any] | None:
        if not isinstance(hour_data, dict):
            return None
        
        subject_data = hour_data.get('Subject')
        if not subject_data or not isinstance(subject_data, dict):
            return None
        
        subject_name = (
            subject_data.get('Name')
            or subject_data.get('Caption')
            or subject_data.get('Abbrev')
            or 'NeznÃ¡mÃ½ pÅ°edmÄºt'
        )
        
        room_data = hour_data.get('Room')
        room_name = None
        if room_data and isinstance(room_data, dict):
            room_name = room_data.get('Name') or room_data.get('Caption')
        
        teacher_data = hour_data.get('Teacher')
        teacher_name = None
        if teacher_data and isinstance(teacher_data, dict):
            teacher_name = teacher_data.get('Name') or teacher_data.get('Caption')
        
        group_data = hour_data.get('Group')
        group_name = None
        if group_data and isinstance(group_data, dict):
            group_name = group_data.get('Name') or group_data.get('Caption')
        
        hour_number = hour_data.get('HourNumber') or hour_data.get('Hour') or 0
        
        external_id = hour_data.get('Id') or hour_data.get('ID')
        if not external_id:
            identity = '|'.join(
                (
                    self.base_url,
                    str(day_index),
                    str(hour_number),
                    str(subject_name).strip(),
                )
            )
            external_id = hashlib.sha256(identity.encode('utf-8')).hexdigest()
        
        return {
            'external_id': str(external_id),
            'day_of_week': day_index,
            'hour': int(hour_number),
            'subject': str(subject_name).strip(),
            'room': str(room_name).strip() if room_name else None,
            'teacher': str(teacher_name).strip() if teacher_name else None,
            'group': str(group_name).strip() if group_name else None,
            'source': 'bakalari',
        }
