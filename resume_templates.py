"""Optional LaTeX templates; fixed compiler commands and escaped candidate fields."""
import hashlib
import re
import shutil
import subprocess
from pathlib import Path
from store import DATA,get_setting,set_setting

BUILTIN=r'''\documentclass[10pt,a4paper]{article}
\usepackage[margin=1.7cm]{geometry}
\usepackage[T1]{fontenc}
\usepackage{hyperref}
\pagestyle{empty}
\begin{document}
\begin{center}{\Large\textbf{ {{name}} }}\\ {{email}} | {{phone}} | {{location}}\end{center}
\section*{Education} {{college}} --- {{degree}}\\Expected graduation: {{graduation_year}}
\section*{Skills} {{skills}}
\section*{Projects and Experience} {{facts}}
\section*{Links} {{links}}
\end{document}'''


def tex_escape(value):
    mapping={'\\':r'\textbackslash{}','&':r'\&','%':r'\%','$':r'\$','#':r'\#','_':r'\_','{':r'\{','}':r'\}','~':r'\textasciitilde{}','^':r'\textasciicircum{}'}
    return ''.join(mapping.get(c,c) for c in str(value))


def render(template,profile,facts):
    values={k:tex_escape(profile.get(k,'')) for k in ('name','email','phone','location','college','degree','graduation_year')}
    values['skills']=tex_escape(', '.join(profile.get('skills',[])))
    values['facts']='\n\n'.join(tex_escape(fact) for fact in facts)
    values['links']=tex_escape(' | '.join(profile.get(k,'') for k in ('github','linkedin','portfolio') if profile.get(k)))
    unknown=set(re.findall(r'{{\s*([A-Za-z_]+)\s*}}',template))-set(values)
    if unknown:raise ValueError('Unknown LaTeX fields: '+', '.join(sorted(unknown)))
    return re.sub(r'{{\s*([A-Za-z_]+)\s*}}',lambda m:values[m[1]],template)


def compile_pdf(source,folder):
    engine=next((shutil.which(name) for name in ('lualatex','xelatex','pdflatex') if shutil.which(name)),None)
    if not engine:raise ValueError('Install MiKTeX/TeX Live with lualatex or xelatex before activating a LaTeX template')
    folder.mkdir(parents=True,exist_ok=True)
    tex=folder/'resume.tex';tex.write_text(source,encoding='utf-8')
    result=subprocess.run([engine,'-no-shell-escape','-interaction=nonstopmode','-halt-on-error','resume.tex'],
        cwd=folder,capture_output=True,timeout=45,check=False)
    if result.returncode or not (folder/'resume.pdf').is_file():
        raise ValueError('LaTeX test compile failed; inspect the local template preview log. No template was activated.')
    return folder/'resume.pdf'


def register(data,filename):
    if len(data)>100000 or not filename.lower().endswith('.tex'):
        raise ValueError('Upload a .tex resume template under 100 KB')
    template=data.decode('utf-8-sig')
    profile=get_setting('profile')
    test={**profile,'name':profile['name'] or 'Template Preview','email':profile['email'] or 'preview@example.com'}
    digest=hashlib.sha256(data).hexdigest()
    folder=DATA/'templates'/digest
    source=render(template,test,test.get('facts') or ['Template compilation preview only.'])
    pdf=compile_pdf(source,folder)
    from pypdf import PdfReader
    reader=PdfReader(pdf)
    extracted='\n'.join(page.extract_text() or '' for page in reader.pages)
    if test['email'] not in extracted or len(reader.pages)>2:
        raise ValueError('Template preview must preserve the email as extractable text and stay within two pages')
    path=folder/'template.tex';path.write_text(template,encoding='utf-8')
    value={'name':Path(filename).name,'path':str(path),'preview':str(pdf)}
    set_setting('resume_template',value)
    return {'activated':True,'name':value['name'],'preview':'/api/templates/preview.pdf'}
