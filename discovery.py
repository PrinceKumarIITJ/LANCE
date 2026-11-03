"""Public career-board adapters; never interpret a job description as instructions."""
import hashlib
import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import httpx
from store import db, get_setting, now, event


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignore = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.ignore += 1
        if tag in ('p', 'br', 'li', 'div', 'h1', 'h2', 'h3'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.ignore = max(0, self.ignore - 1)

    def handle_data(self, data):
        if not self.ignore:
            self.parts.append(data)


def plain(value):
    parser = PlainText()
    parser.feed(html.unescape(value or ''))
    return re.sub(r'\n\s*\n+', '\n', ''.join(parser.parts)).strip()


def public_url(value):
    """No arbitrary fetching. Browser destinations must be public HTTPS hosts."""
    import ipaddress
    parsed = urlsplit(value.strip())
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use a public https:// job URL without embedded credentials')
    host = parsed.hostname.lower()
    if '.' not in host or host.endswith(('.local', '.localhost', '.internal')):
        raise ValueError('Local/private URLs are not supported')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if re.fullmatch(r'[0-9.]+', host):
            raise ValueError('Numeric hosts are not supported')
    else:
        raise ValueError('IP-address URLs are not supported')
    if parsed.port not in (None, 443):
        raise ValueError('Only standard HTTPS destinations are supported')
    return value.strip()


def canonical(url):
    p = urlsplit(public_url(url))
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(('utm_', 'gh_src'))
             and k.lower() not in ('source', 'ref', 'referrer', 'trackingid')]
    return urlunsplit(('https', p.netloc.lower(), p.path.rstrip('/'), urlencode(sorted(query)), ''))


def score_job(item, profile):
    title = item['title'].lower()
    text = plain(item['description']).lower()
    all_text = title + '\n' + text
    reasons, blocked, uncertain = [], False, False
    roles = [r.lower() for r in profile.get('roles', [])]
    ai = bool(re.search(r'\b(ai|ml|llm|machine learning|artificial intelligence)\b', title))
    software = bool(re.search(r'\b(software|sde|backend|full.?stack|developer|engineer)\b', title))
    role_match = (ai and any(re.search(r'\b(ai|ml|machine learning)\b', r) for r in roles)) or (
        software and any(re.search(r'\b(software|sde|backend|developer)\b', r) for r in roles))
    score = 35 if role_match else 0
    reasons.append('Target role match' if role_match else 'Role does not match selected AI/software tracks')
    if not role_match:
        blocked = True
    if re.search(r'\b(senior|staff|principal|lead|manager|director|sr\.?)\b', title):
        blocked = True
        reasons.append('Senior-level title')
    if re.search(r'\b(intern|internship|part.time|contract|temporary)\b', title + ' ' + item.get('employment', '').lower()):
        blocked = True
        reasons.append('Not a permanent full-time role')
    # Only explicit minimum requirements, not incidental project/year references.
    minimums = [int(x) for x in re.findall(r'(?:minimum(?: of)?|at least|requires?)\s+(\d+)\+?\s+years?', text)]
    minimums += [int(x) for x in re.findall(r'\b(\d+)\+?\s+years?\s+(?:of\s+)?(?:professional|industry|commercial|relevant|work)\s+experience', text)]
    minimums += [int(x) for x in re.findall(r'\b(\d+)\s*[-–]\s*\d+\s+years?\s+(?:of\s+)?experience', text)]
    if minimums and max(minimums) > profile.get('experience_months',0)/12:
        blocked = True
        reasons.append('Requires professional experience beyond a fresher profile')
    grad = str(profile.get('graduation_year', 2027))
    grad_sentences = [s for s in re.split(r'[\n.;]', text) if re.search(r'graduat|batch|class of', s)]
    explicit_years = {year for s in grad_sentences for year in re.findall(r'\b20[2-4]\d\b', s)}
    for sentence in grad_sentences:
        for start, end in re.findall(r'\b(20[2-4]\d)\s*(?:to|[-–])\s*(20[2-4]\d)\b', sentence):
            explicit_years.update(str(year) for year in range(int(start), int(end) + 1))
    if explicit_years and grad not in explicit_years:
        blocked = True
        reasons.append(f'Graduation-year requirement does not include {grad}; review wording/ranges')
    elif grad in explicit_years:
        score += 20
        reasons.append(f'{grad} graduate hiring mentioned; verify exact joining date')
    else:
        uncertain = True
        reasons.append(f'{grad} eligibility and joining date need verification')
    early = re.search(r'\b(fresher|new grad|graduate|entry.level|early.career|junior|sde.?1|engineer i)\b', title + ' ' + text)
    if early:
        score += 15
        reasons.append('Early-career hiring signal')
    elif not minimums:
        uncertain = True
        reasons.append('Experience requirements need review')
    matched = [s for s in profile.get('skills', []) if re.search(r'(?<!\w)' + re.escape(s.lower()) + r'(?!\w)', all_text)]
    score += min(25, len(matched) * 5)
    if matched:
        reasons.append('Matching skills: ' + ', '.join(matched))
    locations = profile.get('locations', [])
    if not locations:
        uncertain = True
        reasons.append('Set location and work-authorization preferences')
    elif 'remote' in item['location'].lower():
        uncertain = True
        reasons.append('Remote role: verify hiring from India and country/work-authorization restrictions')
        if any(loc.lower() == 'remote' for loc in locations):
            score += 5
    elif any(loc.lower() in item['location'].lower() for loc in locations):
        score += 5
    elif any(loc.lower() == 'india' for loc in locations) and re.search(r'\b(bengaluru|bangalore|hyderabad|pune|mumbai|delhi|gurugram|gurgaon|noida|chennai|kolkata|ahmedabad)\b', item['location'], re.I):
        score += 5
    else:
        uncertain = True
        reasons.append('Location/work authorization needs review (remote may be country-restricted)')
    if not profile.get('available_from'):
        uncertain = True
        reasons.append('Set your earliest full-time joining date')
    if not re.search(r'full[\s-]?time|permanent',all_text+' '+item.get('employment',''),re.I):
        uncertain=True
        reasons.append('Employment type must be verified as full-time')
    return min(score, 100), 'blocked' if blocked else ('review' if uncertain else 'potential'), reasons


def ingest(item):
    import json
    item['url'] = canonical(item['url'])
    item['description'] = plain(item['description'])[:100000]
    score, eligibility, reasons = score_job(item, get_setting('profile'))
    fingerprint = hashlib.sha256(item['url'].encode()).hexdigest()
    with db() as con:
        old = con.execute('SELECT * FROM jobs WHERE fingerprint=?', (fingerprint,)).fetchone()
        if old and old['status'] in ('prepared', 'ready', 'assisted', 'needs_input', 'auto_running') and any(
                old[key] != item.get(key,'') for key in ('title', 'location', 'description','employment')):
            con.execute("UPDATE jobs SET status='new',packet=NULL,updated_at=? WHERE id=?", (now(), old['id']))
            con.execute("DELETE FROM outbox WHERE job_id=? AND status IN ('draft','queued')", (old['id'],))
        con.execute('''INSERT INTO jobs(fingerprint,company,title,location,url,description,provider,
          published,fetched_at,score,eligibility,reasons,updated_at,employment) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(fingerprint) DO UPDATE SET description=excluded.description,
          title=excluded.title,location=excluded.location,fetched_at=excluded.fetched_at,
          score=excluded.score,eligibility=excluded.eligibility,reasons=excluded.reasons,employment=excluded.employment''',
          (fingerprint, item['company'], item['title'], item['location'], item['url'],
           item['description'], item['provider'], item.get('published'), now(), score,
           eligibility, json.dumps(reasons), now(),item.get('employment','')))
        job_id=con.execute('SELECT id FROM jobs WHERE fingerprint=?', (fingerprint,)).fetchone()[0]
    from evaluation import save_assessment
    save_assessment(job_id,item)
    return job_id


async def fetch_board(source, transport=None):
    provider, board = source['provider'], source['board']
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', board):
        raise ValueError('Board must be the company slug, not a full URL')
    urls = {
      'greenhouse': f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true',
      'lever': f'https://api.lever.co/v0/postings/{board}?mode=json',
      'ashby': f'https://api.ashbyhq.com/posting-api/job-board/{board}',
    }
    if provider not in urls:
        raise ValueError('Supported board providers: greenhouse, lever, ashby')
    async with httpx.AsyncClient(timeout=35, transport=transport) as client:
        response = await client.get(urls[provider], headers={'User-Agent': 'JobPilot/0.1 personal job search'})
        response.raise_for_status()
        data = response.json()
    raw = data if provider == 'lever' else data['jobs']
    items = []
    for row in raw:
        if provider == 'greenhouse':
            item = dict(title=row['title'], location=(row.get('location') or {}).get('name', ''),
                        url=row['absolute_url'], description=row.get('content', ''), published=row.get('updated_at'))
        elif provider == 'lever':
            desc = row.get('descriptionPlain', '') + '\n' + '\n'.join(
                f"{p.get('text', '')}\n{plain(p.get('content', ''))}" for p in row.get('lists', []))
            item = dict(title=row['text'], location=(row.get('categories') or {}).get('location', ''),
                        url=row.get('applyUrl') or row['hostedUrl'], description=desc,
                        employment=(row.get('categories') or {}).get('commitment', ''))
        else:
            if row.get('isListed') is False:
                continue
            item = dict(title=row['title'], location=row.get('location', ''),
                        url=row.get('applyUrl') or row['jobUrl'],
                        description=row.get('descriptionPlain') or row.get('descriptionHtml', ''),
                        employment=row.get('employmentType', ''), published=row.get('publishedAt'))
        item.update(company=source['company'], provider=provider)
        items.append(item)
    return items


async def sync_sources():
    from store import rows
    results = []
    for source in rows('SELECT * FROM sources WHERE enabled=1'):
        try:
            items = await fetch_board(source)
            for item in items:
                ingest(item)
            error, count = None, len(items)
        except Exception as exc:
            error, count = f'{type(exc).__name__}: {str(exc)[:250]}', 0
        with db() as con:
            con.execute('UPDATE sources SET checked_at=?,error=? WHERE id=?', (now(), error, source['id']))
        results.append(dict(company=source['company'], count=count, error=error))
    event('discovery', str(results))
    return results
