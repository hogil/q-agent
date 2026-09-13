import json,tempfile,shutil
from pathlib import Path
from skill_loader import compile_prompt
P=Path(__file__).resolve().parent
checks=[]
def check(name,b):assert b,name;checks.append({'name':name,'passed':True})
for role in ['router','answer','judge']:
 a=compile_prompt(role,['lots']);b=compile_prompt(role,['lots'])
 check(role+' stable prompt',a['prompt_sha256']==b['prompt_sha256'])
 check(role+' has shared lot skill','skills/quality-lot-retrieval/SKILL.md' in a['loaded_files'])
 check(role+' no unrelated document skill',not any('document-evidence' in x for x in a['loaded_files']))
 check(role+' dictionary not bulk loaded',not any('domain-data' in x for x in a['loaded_files']))
check('deduplicate shared schema',compile_prompt('router',['schema','lots'])['loaded_files'].count('skills/quality-incident-schema/SKILL.md')==1)
try:compile_prompt('judge',['maintenance']);rejected=False
except ValueError:rejected=True
check('online judge cannot load maintenance',rejected)
with tempfile.TemporaryDirectory() as d:
 root=Path(d)/'release';shutil.copytree(P,root,ignore=shutil.ignore_patterns('.git','__pycache__'))
 f=root/'skills/quality-core/SKILL.md';f.write_text(f.read_text()+'\nchanged')
 try:compile_prompt('router',['lots'],root);blocked=False
 except ValueError:blocked=True
 check('modified skill rejected by locked release',blocked)
for f in (P/'skills').glob('*/SKILL.md'):
 text=f.read_text();check('skill metadata '+f.parent.name,text.startswith('---\nname: '+f.parent.name+'\ndescription: ') and text.count('---')>=2)
(P/'skill_checks.json').write_text(json.dumps({'notice':'컴파일/무결성 검증. 실제 LLM 역할 품질 평가 아님.','checks':checks},ensure_ascii=False,indent=2))
print(json.dumps({'skill_checks':len(checks)}))
