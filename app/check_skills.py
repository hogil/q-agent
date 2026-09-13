import json,tempfile,shutil
from pathlib import Path
from skill_loader import compile_prompt,release_files
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
 for newline in [b'\n',b'\r\n']:
  for f in release_files(root).values():
   f.write_bytes(f.read_bytes().replace(b'\r\n',b'\n').replace(b'\n',newline))
  check('checkout line endings preserve prompt '+repr(newline),compile_prompt('router',['lots'],root)['prompt_sha256']==compile_prompt('router',['lots'])['prompt_sha256'])
 f=root/'skills/quality-core/SKILL.md';f.write_text(f.read_text()+'\nchanged')
 try:compile_prompt('router',['lots'],root);blocked=False
 except ValueError:blocked=True
 check('modified skill rejected by locked release',blocked)
for f in (P/'skills').glob('*/SKILL.md'):
 text=f.read_text();check('skill metadata '+f.parent.name,text.startswith('---\nname: '+f.parent.name+'\ndescription: ') and text.count('---')>=2)
for role in ['router','judge','answer']:
 compiled=compile_prompt(role,['incident_search'])
 check(role+' includes persona instructions','## 페르소나' in compiled['system_prompt'])
 check(role+' includes shared working style','skills/quality-core/references/working-style.md' in compiled['loaded_files'])
 for topics in [['incident_search'],['incident_search','schema'],['incident_search','lots','documents'],['incident_search','wafers'],['incident_search','statistics']]:
  profile=compile_prompt(role,topics)
  check(role+' profile within character budget '+','.join(topics),len(profile['system_prompt'])<=json.loads((P/'skill_registry.json').read_text())['max_prompt_characters'])
(P/'skill_checks.json').write_text(json.dumps({'notice':'컴파일/무결성 검증. 실제 LLM 역할 품질 평가 아님.','checks':checks},ensure_ascii=False,indent=2))
print(json.dumps({'skill_checks':len(checks)}))
