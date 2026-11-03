import html
import io
import json
import zipfile
from pathlib import Path
from store import DATA,rows,job,now


def html_report():
    jobs=rows('SELECT * FROM jobs ORDER BY updated_at DESC')
    stage_counts={stage:sum(j['status']==stage for j in jobs) for stage in sorted({j['status'] for j in jobs})}
    escape=html.escape
    table=''.join('<tr>'+''.join(f'<td>{escape(str(item[key]))}</td>' for key in ('company','title','location','score','eligibility','status','updated_at'))+'</tr>' for item in jobs)
    stats=''.join(f'<div class="stat"><strong>{count}</strong>{escape(stage)}</div>' for stage,count in stage_counts.items())
    sent=rows("SELECT count(*) AS count FROM campaign_messages WHERE status='sent'")[0]['count']+rows("SELECT count(*) AS count FROM outbox WHERE status='sent'")[0]['count']
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LANCE application report</title>
    <style>body{{font:14px system-ui;background:#f4f6ef;color:#233b3d;margin:35px}}h1{{font-size:28px}}.stats{{display:flex;gap:12px;flex-wrap:wrap}}.stat{{padding:18px;background:white;border:1px solid #dce4d6;border-radius:10px;min-width:110px}}strong{{display:block;font-size:24px}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #e1e6dd}}input{{margin:22px 0;padding:12px;width:min(500px,90%)}}.table{{overflow-x:auto}}</style>
    <h1>LANCE · Application report</h1><p>Generated {escape(now())} · {len(jobs)} jobs · {sent} emails accepted by your sender</p><div class="stats">{stats}</div><input id="filter" placeholder="Filter by company, role, stage or location" aria-label="Filter applications"><div class="table"><table><thead><tr><th>Company</th><th>Role</th><th>Location</th><th>Score</th><th>Eligibility</th><th>Stage</th><th>Updated (UTC)</th></tr></thead><tbody>{table}</tbody></table></div><p>Scores and reply signals require review. This report is self-contained and works offline.</p><script>document.querySelector('#filter').addEventListener('input',e=>{{const q=e.target.value.toLowerCase();document.querySelectorAll('tbody tr').forEach(row=>row.hidden=!row.innerText.toLowerCase().includes(q));}});</script></html>'''


def archive(job_id):
    item=job(job_id);buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr('job.json',json.dumps(item,indent=2))
        output.writestr('activity.json',json.dumps(rows('SELECT * FROM events WHERE job_id=? ORDER BY id',(job_id,)),indent=2))
        output.writestr('preparation.json',json.dumps(rows('SELECT * FROM artifacts WHERE job_id=?',(job_id,)),indent=2))
        if item.get('packet'):
            root=Path(item['packet']).resolve()
            if root.is_relative_to(DATA.resolve()):
                for filename in ('resume.pdf','cover-letter.pdf','cover-letter.txt','manifest.json','review.json','resume.tex'):
                    path=root/filename
                    if path.is_file():output.write(path,'materials/'+filename)
        evidence=DATA/'evidence'/f'{job_id}.png'
        if evidence.is_file():output.write(evidence,'submission-confirmation.png')
    return buffer.getvalue()
