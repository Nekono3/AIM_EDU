"""
Utility functions for schools app.
Handles Excel file parsing and Smart ID matching.
"""
import openpyxl
from django.utils.translation import gettext_lazy as _


def _resolve_class_type(row, column_mapping, section_str):
    """
    Resolve class_type from Excel column or auto-detect from section name.

    Returns a tuple (class_type, source) where source is:
      - 'explicit'  — read from the class_type column
      - 'auto'      — auto-detected from section name
      - 'invalid'   — column exists but value is empty / unrecognised
    """
    if 'class_type' in column_mapping:
        try:
            raw = str(row[column_mapping['class_type']] or '').strip().lower()
            if raw in ('kg', 'кг'):
                return ('kg', 'explicit')
            if raw in ('ru', 'ру'):
                return ('ru', 'explicit')
            # Column present but value unrecognised or empty
            return (None, 'invalid')
        except IndexError:
            return (None, 'invalid')

    # No class_type column — auto-detect from section name
    section_lower = section_str.lower()
    if 'кг' in section_lower or 'kg' in section_lower:
        return ('kg', 'auto')
    return ('ru', 'auto')


def parse_master_student_excel(file):
    """
    Parse Master Student List Excel file.

    Returns:
        dict with keys:
          - 'students': list of student dicts
          - 'has_class_type_column': bool
          - 'auto_detected_count': int  (students whose type was guessed)
          - 'invalid_rows': list of (row_number, raw_value) with bad class_type
          - 'kg_count': int
          - 'ru_count': int

    Raises:
        ValueError if file format is invalid
    """
    try:
        wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
        ws = wb.active

        # Get headers from first row
        headers = []
        for cell in ws[1]:
            if cell.value:
                headers.append(str(cell.value).lower().strip())
            else:
                headers.append('')

        # Map column names to expected fields
        column_mapping = {}

        # Student ID
        for i, h in enumerate(headers):
            if h in ['id', 'student_id', 'studentid', 'id студента', 'ид', 'student id']:
                column_mapping['student_id'] = i
                break

        # Name
        for i, h in enumerate(headers):
            if h in ['name', 'first_name', 'firstname', 'имя', 'first name']:
                column_mapping['name'] = i
                break

        # Surname
        for i, h in enumerate(headers):
            if h in ['surname', 'last_name', 'lastname', 'фамилия', 'last name']:
                column_mapping['surname'] = i
                break

        # Grade/Class
        for i, h in enumerate(headers):
            if h in ['class', 'grade', 'класс', 'class/grade']:
                column_mapping['grade'] = i
                break

        # Section
        for i, h in enumerate(headers):
            if h in ['section', 'группа', 'секция', 'group']:
                column_mapping['section'] = i
                break

        # Class Type
        for i, h in enumerate(headers):
            if h in ['class_type', 'classtype', 'type', 'тип класса', 'тип']:
                column_mapping['class_type'] = i
                break

        # Validate required columns
        required = ['student_id', 'name', 'surname', 'grade', 'section']
        missing = [col for col in required if col not in column_mapping]

        if missing:
            raise ValueError(
                _('Missing required columns: %(columns)s. Found headers: %(headers)s') % {
                    'columns': ', '.join(missing),
                    'headers': ', '.join(headers)
                }
            )

        has_class_type_column = 'class_type' in column_mapping

        # Parse rows
        students = []
        auto_detected_count = 0
        invalid_rows = []
        kg_count = 0
        ru_count = 0

        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            # Skip empty rows
            if not row or not any(row):
                continue

            try:
                student_id = row[column_mapping['student_id']]
                name = row[column_mapping['name']]
                surname = row[column_mapping['surname']]
                grade = row[column_mapping['grade']]
                section = row[column_mapping['section']]

                # Skip if no student ID
                if not student_id:
                    continue

                section_str = str(section).strip() if section else ''
                class_type, source = _resolve_class_type(
                    row, column_mapping, section_str
                )

                if source == 'auto':
                    auto_detected_count += 1
                elif source == 'invalid':
                    raw_val = ''
                    if has_class_type_column:
                        try:
                            raw_val = str(row[column_mapping['class_type']] or '')
                        except IndexError:
                            pass
                    invalid_rows.append((row_idx, raw_val, str(student_id).strip()))
                    # Default to 'ru' so import can still proceed (view will warn)
                    class_type = 'ru'

                if class_type == 'kg':
                    kg_count += 1
                else:
                    ru_count += 1

                students.append({
                    'student_id': str(student_id).strip(),
                    'name': str(name).strip() if name else '',
                    'surname': str(surname).strip() if surname else '',
                    'grade': str(grade).strip() if grade else '',
                    'section': section_str,
                    'class_type': class_type,
                })
            except IndexError:
                continue  # Skip incomplete rows

        wb.close()
        return {
            'students': students,
            'has_class_type_column': has_class_type_column,
            'auto_detected_count': auto_detected_count,
            'invalid_rows': invalid_rows,
            'kg_count': kg_count,
            'ru_count': ru_count,
        }

    except Exception as e:
        if 'Missing required columns' in str(e):
            raise
        raise ValueError(_('Error reading Excel file: %(error)s') % {'error': str(e)})


def normalize_student_id(raw_id):
    """
    Normalize student ID by removing leading zeros.
    Handles both string and integer inputs.
    
    Examples:
        '01251001' -> '1251001'
        '1251001' -> '1251001'
        1251001 -> '1251001'
    """
    try:
        # Convert to string, strip whitespace, convert to int to remove leading zeros
        return str(int(str(raw_id).strip()))
    except (ValueError, TypeError):
        # If conversion fails, just return stripped string
        return str(raw_id).strip()


def find_student_by_id(school, raw_student_id):
    """
    Find a MasterStudent by ID, handling leading zero discrepancies.
    
    Args:
        school: School instance
        raw_student_id: Student ID from ZipGrade (may have different format)
    
    Returns:
        MasterStudent instance or None if not found
    """
    from .models import MasterStudent
    
    normalized_id = normalize_student_id(raw_student_id)
    
    # Try to find by normalized ID
    student = MasterStudent.objects.filter(
        school=school,
        student_id_normalized=normalized_id
    ).first()
    
    return student
