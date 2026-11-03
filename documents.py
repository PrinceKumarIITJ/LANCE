import hashlib
import io
import re
import zipfile
from pathlib import Path
from pypdf import PdfReader
from docx import Document
from store import DATA, db, rows, get_setting, now


def add(data,filename):
    filename=Path(filename.replace('\\','/')).name[:180]
    suffix=Path(filename).suffix.lower()
    if len(data)>8*1024*1024:
        raise ValueError('Documents must be under 8 MB')
    if suffix=='.pdf':
        reader=PdfReader(io.BytesIO(data))
        if len(reader.pages)>30:
            raise ValueError('Document must be 30 pages or fewer')
        text='\n'.join(page.extract_text() or '' for page in reader.pages)
    elif suffix=='.docx':
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(i.file_size for i in archive.infolist())>30*1024*1024:
                raise ValueError('Expanded DOCX is too large')
        text='\n'.join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    elif suffix in ('.txt','.md'):
        text=data.decode('utf-8-sig')
    else:
        raise ValueError('Supported documents: PDF, DOCX, TXT, MD')
    digest=hashlib.sha256(data).hexdigest()
    folder=DATA/'documents';folder.mkdir(exist_ok=True)
    path=folder/(digest+suffix)
    path.write_bytes(data)
    with db() as con:
        con.execute('INSERT OR IGNORE INTO documents(name,digest,text,path,created_at) VALUES (?,?,?,?,?)',(filename,digest,text[:100000],str(path),now()))
    return {'name':filename,'text':text[:100000],'message':'Evidence imported. Review suggestions before updating your profile.'}


def suggestions():
    evidence=rows('SELECT id,name,text FROM documents')
    profile=get_setting('profile')
    if profile.get('resume'):
        evidence.append({'id':'resume','name':'Uploaded resume','text':profile['resume']['text']})
    result=[]
    for doc in evidence:
        text=doc['text']
        for value in dict.fromkeys(re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',text)):
            result.append({'field':'email','value':value,'source':doc['name'],'evidence':value})
        for kind,pattern in [('github',r'https?://(?:www\.)?github\.com/[A-Za-z0-9_-]+'),('linkedin',r'https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+')]:
            for value in dict.fromkeys(re.findall(pattern,text)):
                result.append({'field':kind,'value':value,'source':doc['name'],'evidence':value})
        for line in text.splitlines():
            line=line.strip(' •\t-')
            if 35<=len(line)<=500 and re.search(r'\b(built|developed|implemented|trained|designed|created|deployed|optimized)\b',line,re.I):
                result.append({'field':'fact_candidate','value':line,'source':doc['name'],'evidence':line})
    return {'suggestions':result[:100],'note':'These are verbatim evidence spans, not verified claims. Check ownership, dates and context before adding them to your profile.'}
