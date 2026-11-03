"""Five dimensions with explicit unknowns; eligibility remains a separate gate."""
import json
import re
from store import db, rows, get_setting, now
from discovery import score_job

SKILLS={
 'Python':'https://docs.python.org/3/tutorial/',
 'PyTorch':'https://pytorch.org/tutorials/',
 'TensorFlow':'https://www.tensorflow.org/tutorials',
 'SQL':'https://www.postgresql.org/docs/current/tutorial.html',
 'JavaScript':'https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide',
 'TypeScript':'https://www.typescriptlang.org/docs/handbook/',
 'React':'https://react.dev/learn',
 'Java':'https://dev.java/learn/',
 'C++':'https://isocpp.org/get-started',
 'Docker':'https://docs.docker.com/get-started/',
 'Kubernetes':'https://kubernetes.io/docs/tutorials/',
 'Git':'https://git-scm.com/doc',
 'Linux':'https://docs.kernel.org/',
 'FastAPI':'https://fastapi.tiangolo.com/tutorial/',
 'AWS':'https://docs.aws.amazon.com/',
 'PostgreSQL':'https://www.postgresql.org/docs/current/tutorial.html',
 'Redis':'https://redis.io/docs/latest/develop/',
 'Transformers':'https://huggingface.co/docs/transformers/',
 'LangChain':'https://docs.langchain.com/',
 'RAG':'https://huggingface.co/learn/cookbook/advanced_rag',
 'scikit-learn':'https://scikit-learn.org/stable/user_guide.html',
}


def mentioned(skill,text):
    return bool(re.search(r'(?<!\w)'+re.escape(skill.lower())+r'(?!\w)',text.lower()))


def evaluate(item,profile=None):
    profile=profile or get_setting('profile')
    _,eligibility,reasons=score_job(item,profile)
    text=item['title']+'\n'+item['description']
    requirements=[skill for skill in SKILLS if mentioned(skill,text)]
    known='\n'.join(profile.get('skills',[])+profile.get('facts',[]))
    matches=[skill for skill in requirements if mentioned(skill,known)]
    gaps=[skill for skill in requirements if skill not in matches]
    technical=round(30*len(matches)/len(requirements),1) if requirements else 15
    minimums=[int(v) for v in re.findall(r'\b(\d+)\+?\s+years?\s+(?:of\s+)?(?:professional|industry|work|relevant)\s+experience',text.lower())]
    experience=25 if re.search(r'graduate|entry.level|fresher|junior|early.career',text,re.I) else 12.5
    if minimums:
        experience=round(25*min(1,profile.get('experience_months',0)/(12*max(minimums))),1)
    prefs=profile.get('work_preferences',[])
    behavioral=round(15*sum(mentioned(p,text) for p in prefs)/len(prefs),1) if prefs else 7.5
    career=30 if 'Target role match' in reasons else 0
    dimensions={
      'technical':{'score':technical,'max':30,'evidence':matches,'unknown':not bool(requirements)},
      'experience':{'score':experience,'max':25,'candidate_months':profile.get('experience_months',0),'explicit_required_years':minimums},
      'work_preferences':{'score':behavioral,'max':15,'unknown':not bool(prefs),'note':'Self-reported preferences; no personality inference'},
      'career_alignment':{'score':career,'max':30,'roles':profile.get('roles',[])},
      'location':{'gate':'review' if any('location' in r.lower() or 'country' in r.lower() or 'remote role' in r.lower() for r in reasons) else 'potential','location':item['location']}}
    return {'score':round(technical+experience+behavioral+career),'eligibility':eligibility,
        'reasons':reasons,'dimensions':dimensions,'skill_gaps':gaps,'mentioned_skills':requirements,
        'salary':{'status':'No verified salary benchmark configured; use the original advertised compensation'},'evaluated_at':now()}


def save_assessment(job_id,item=None):
    if item is None:
        from store import job
        item=job(job_id)
    assessment=evaluate(item)
    with db() as con:
        con.execute('INSERT OR REPLACE INTO assessments VALUES (?,?)',(job_id,json.dumps(assessment)))
        con.execute('UPDATE jobs SET score=?,eligibility=?,reasons=? WHERE id=?',
            (assessment['score'],assessment['eligibility'],json.dumps(assessment['reasons']),job_id))
    return assessment


def rank_all():
    ranked=[{'id':item['id'],**save_assessment(item['id'],item)} for item in rows('SELECT * FROM jobs')]
    return sorted(ranked,key=lambda x:(x['eligibility']=='blocked',-x['score']))


def skill_plan(job_id=None):
    jobs=rows('SELECT * FROM jobs WHERE id=?',(job_id,)) if job_id else rows("SELECT * FROM jobs WHERE eligibility!='blocked' AND status!='archived'")
    if not jobs:
        raise ValueError('Import suitable jobs before generating a skill plan')
    counts={}
    for item in jobs:
        for skill in evaluate(item)['skill_gaps']:
            counts[skill]=counts.get(skill,0)+1
    return {'jobs_analyzed':len(jobs),'gaps':[{'skill':skill,'postings':count,
        'priority':'high' if count/len(jobs)>=.5 else 'medium','resource':SKILLS[skill],
        'suggested_practice':'Build a small project and document your own implementation and evaluation',
        'planning_hours':'8–20 (rough planning range; depends on your starting level)'}
        for skill,count in sorted(counts.items(),key=lambda pair:-pair[1])],
        'note':'Mentioned skills are not all mandatory. Verify requirements; gap estimates are heuristics, not measured proficiency.'}
