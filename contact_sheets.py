"""Normalize single addresses, CSV and XLSX sheets without evaluating formulas."""
import csv
import io
import re
import zipfile
from openpyxl import load_workbook
from outreach import valid_email
from store import db

ALIASES = {
    'email': {'email', 'emailid', 'emailaddress', 'mail', 'mailid', 'hrmail', 'hremail', 'recruiteremail'},
    'name': {'name', 'hrname', 'recruiter', 'recruitername', 'contactname'},
    'company': {'company', 'companyname', 'organisation', 'organization', 'employer'},
    'source': {'source', 'sourceurl', 'reference', 'url'},
}


def header(value):
    key = re.sub(r'[^a-z]', '', str(value or '').lower())
    return next((name for name, values in ALIASES.items() if key in values), key)


def parse(data, filename):
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('Contact sheet must be under 8 MB')
    if filename.lower().endswith('.xlsx'):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if len(archive.infolist()) > 2000 or sum(i.file_size for i in archive.infolist()) > 30 * 1024 * 1024:
                    raise ValueError('Workbook expands beyond the supported size')
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
            sheet = book.active
            if sheet.max_row and sheet.max_row > 5000:
                raise ValueError('Sheet supports at most 2000 contacts (remove excessive blank/formatted rows)')
            values = list(sheet.iter_rows(max_row=2002, max_col=40, values_only=True))
            book.close()
        except (zipfile.BadZipFile, KeyError, OSError):
            raise ValueError('Invalid XLSX workbook; export a fresh .xlsx or CSV')
    else:
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ValueError('Export your CSV as UTF-8')
        try:
            dialect = csv.Sniffer().sniff(text[:4000], delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        values = list(csv.reader(io.StringIO(text), dialect))
    if not values:
        raise ValueError('Sheet is empty')
    names = [header(v) for v in values[0]]
    if 'email' not in names:
        raise ValueError('A column named Email, Email ID, HR Email or Mail ID is required')
    records, errors, seen, duplicates = [], [], set(), 0
    for number, row in enumerate(values[1:], start=2):
        if not any(v is not None and str(v).strip() for v in row):
            continue
        record = {names[i]: str(v or '').strip() for i, v in enumerate(row[:len(names)])}
        try:
            email = valid_email(record.get('email', ''))
        except ValueError:
            errors.append({'row': number, 'error': 'Invalid/missing email (formulas are not evaluated)'})
            continue
        if email in seen:
            duplicates += 1
            continue
        seen.add(email)
        records.append({'email': email, 'name': record.get('name', '')[:150],
            'company': record.get('company', '')[:200], 'source': record.get('source') or 'user-provided sheet'})
        if len(records) > 2000:
            raise ValueError('Import at most 2000 unique contacts per sheet')
    if not records:
        raise ValueError('No valid email addresses found in this sheet')
    return {'contacts': records, 'errors': errors, 'duplicates': duplicates}


def save(records):
    with db() as con:
        for item in records:
            email = valid_email(item['email'])
            con.execute('''INSERT INTO contacts(email,name,company,source) VALUES (?,?,?,?)
              ON CONFLICT(email) DO UPDATE SET name=excluded.name,company=excluded.company,source=excluded.source''',
              (email, item.get('name', '')[:150], item.get('company', '')[:200], item.get('source') or 'user-provided'))
    return len(records)
