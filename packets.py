"""Evidence-preserving tailoring: select/reorder supplied facts; never invent claims."""
import json
import os
import re
from pathlib import Path
from xml.sax.saxutils import escape
import httpx
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from store import DATA, db, job, get_setting, now, event


def validate_profile(profile):
    missing = [key for key in ('name', 'email', 'college', 'available_from') if not profile.get(key)]
    if not profile.get('skills'):
        missing.append('skills')
    if not profile.get('facts'):
        missing.append('verified project/experience facts')
    if missing:
        raise ValueError('Complete your profile first: ' + ', '.join(missing))


async def ordered_facts(profile, posting):
    import intelligence
    facts = profile.get('facts', [])
    tokens = set(re.findall(r'[a-z0-9+#.]+', posting.lower()))
    ranked = sorted(range(len(facts)), key=lambda i: len(tokens & set(re.findall(r'[a-z0-9+#.]+', facts[i].lower()))), reverse=True)
    method = 'Keyword overlap; original facts preserved verbatim'
    config=intelligence.status()
    if config['configured']:
        # Local model only; external content can select IDs, never write candidate claims.
        try:
            response=await intelligence.structured('Rank candidate fact IDs by relevance. Return only IDs; do not write or modify facts.',
                {'candidate_facts':dict(enumerate(facts)),'job_description':posting[:16000]},
                {'type':'object','properties':{'ids':{'type':'array','items':{'type':'integer'}}},'required':['ids'],'additionalProperties':False})
            ids=response['ids']
            if not isinstance(ids, list) or any(type(i) is not int or i < 0 or i >= len(facts) for i in ids) or len(set(ids)) != len(ids):
                raise ValueError('Invalid fact IDs')
            ranked = ids + [i for i in ranked if i not in ids]
            method = f"{config['provider']} ({config['model']}); only verified fact IDs accepted"
        except Exception:
            method += '; local AI unavailable or invalid, deterministic fallback used'
    return [facts[i] for i in ranked], method


async def prepare(job_id):
    item, profile = job(job_id), get_setting('profile')
    if item['status'] in ('submitted', 'submitting', 'uncertain'):
        raise ValueError('Cannot replace materials for a submitted or uncertain application')
    validate_profile(profile)
    facts, method = await ordered_facts(profile, item['title'] + '\n' + item['description'])
    folder = DATA / 'packets' / str(job_id)
    folder.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles['Title'].textColor = colors.HexColor('#16374b')
    body = styles['BodyText']
    body.fontSize, body.leading = 10, 14
    story = [Paragraph(escape(profile['name']), styles['Title'])]
    contact = ' | '.join(str(profile.get(k, '')) for k in ('email', 'phone', 'location') if profile.get(k))
    story += [Paragraph(escape(contact), body), Spacer(1, 4 * mm)]
    for label, content in [
        ('Education', f"{profile['college']} — {profile.get('degree', 'Computer Science')}\nExpected graduation: {profile['graduation_year']}"),
        ('Skills', ', '.join(profile['skills'])),
    ]:
        story += [Paragraph(label, styles['Heading2']), Paragraph(escape(content).replace('\n', '<br/>'), body)]
    links = [profile.get(k) for k in ('github', 'linkedin', 'portfolio') if profile.get(k)]
    if links:
        story += [Paragraph('Links', styles['Heading2']), Paragraph(escape(' | '.join(links)), body)]
    story += [Paragraph('Projects and experience', styles['Heading2'])]
    for fact in facts:
        story += [Paragraph(escape(fact).replace('\n', '<br/>'), body), Spacer(1, 3 * mm)]
    SimpleDocTemplate(str(folder / 'resume.pdf'), pagesize=A4, rightMargin=17 * mm,
                      leftMargin=17 * mm, topMargin=15 * mm, bottomMargin=15 * mm).build(story)
    import resume_templates
    template=get_setting('resume_template')
    source_template=resume_templates.BUILTIN
    if template:
        template_path=Path(template['path']).resolve()
        if not template_path.is_relative_to(DATA.resolve()):raise ValueError('Invalid template path')
        source_template=template_path.read_text(encoding='utf-8')
    tex=resume_templates.render(source_template,profile,facts)
    (folder/'resume.tex').write_text(tex,encoding='utf-8')
    if template:
        resume_templates.compile_pdf(tex,folder)
    cover = (f"Dear {item['company']} hiring team,\n\n"
             f"I would like to apply for the {item['title']} position. I am pursuing "
             f"{profile.get('degree', 'Computer Science')} at {profile['college']}, "
             f"with expected graduation in {profile['graduation_year']}. "
             f"My earliest full-time joining date is {profile['available_from']}.\n\n"
             'Relevant work from my profile:\n' + '\n'.join('- ' + f for f in facts[:3]) +
             f"\n\nPlease find my resume attached. I would welcome a conversation about the role and eligibility.\n\nRegards,\n{profile['name']}\n{profile['email']}")
    (folder / 'cover-letter.txt').write_text(cover, encoding='utf-8')
    cover_story=[Paragraph(escape(line) or ' ',body) if line else Spacer(1,3*mm) for line in cover.splitlines()]
    SimpleDocTemplate(str(folder/'cover-letter.pdf'),pagesize=A4,leftMargin=18*mm,rightMargin=18*mm,topMargin=17*mm,bottomMargin=17*mm).build(cover_story)
    from pypdf import PdfReader
    reader=PdfReader(folder/'resume.pdf')
    parsed='\n'.join(page.extract_text() or '' for page in reader.pages)
    issues=[]
    if len(reader.pages)>2:issues.append('Resume exceeds the 2-page budget; shorten your verified fact list')
    if profile['email'].casefold() not in parsed.casefold():issues.append('Resume email did not survive text extraction')
    if set(facts)!=set(profile['facts']):issues.append('Fact integrity check failed')
    missing_facts=[fact for fact in facts if re.sub(r'\s+','',fact).casefold() not in re.sub(r'\s+','',parsed).casefold()]
    if missing_facts:issues.append('Some fact characters did not survive PDF extraction; review Unicode/font support')
    review={'passed':not issues,'issues':issues,'resume_pages':len(reader.pages),'ats_text_extractable':bool(parsed.strip()),
        'fact_integrity':'Verified facts preserved verbatim','reviewer':'Independent deterministic PDF/text checks; visual candidate review still required','reviewed_at':now()}
    (folder/'review.json').write_text(json.dumps(review,indent=2),encoding='utf-8')
    manifest = {'job_id': job_id, 'created_at': now(), 'method': method, 'facts': facts,
                'profile_snapshot': profile, 'job_url': item['url'], 'cover_letter': cover,'review':review}
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    with db() as con:
        con.execute("UPDATE jobs SET packet=?,status='prepared',updated_at=? WHERE id=?", (str(folder), now(), job_id))
    event('packet_prepared', method, job_id)
    return manifest


def packet_path(job_id, filename='resume.pdf'):
    item = job(job_id)
    if not item['packet']:
        raise ValueError('Prepare application materials first')
    path = Path(item['packet']) / filename
    if not path.is_file() or not path.resolve().is_relative_to(DATA):
        raise ValueError('Application material not found')
    return path
