"""Application-side Skill compiler. No model calls. Explicit freeze is a build step.
python skill_loader.py freeze
python skill_loader.py router --topics terminology,lots
"""
import argparse,json,hashlib
from pathlib import Path
P=Path(__file__).resolve().parent

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def locations(root,settings=None):
 if settings is None:return {'skills_root':root/'skills','dictionary_root':root/'domain-data','registry_file':root/'skill_registry.json','skill_lock_file':root/'release.lock.json'}
 return {key:Path(settings.data['paths'][key]) for key in ('skills_root','dictionary_root','registry_file','skill_lock_file')}
def release_files(root,settings=None):
 paths=locations(root,settings);files={}
 for label,key in [('skills','skills_root'),('domain-data','dictionary_root')]:
  if not paths[key].is_dir():raise ValueError('RELEASE_DIRECTORY_MISSING: '+key)
  for f in sorted(paths[key].rglob('*')):
   if f.is_file():files[label+'/'+str(f.relative_to(paths[key]))]=f
 files['skill_registry.json']=paths['registry_file']
 for name in ['incident_tools.py','incident_filters.py','terminology.py','variant_query_demo.py','prompt_contracts.py','skill_loader.py','config_loader.py','runtime_factory.py']:
  files[name]=root/name
 return files
def freeze(root=P,settings=None):
 # Explicit build operation; not called automatically by compile after changes.
 paths=locations(root,settings)
 manifest={'release':json.loads(paths['registry_file'].read_text())['release'],'files':{name:digest(f) for name,f in release_files(root,settings).items()}}
 paths['skill_lock_file'].write_text(json.dumps(manifest,ensure_ascii=False,indent=2));return manifest

def compile_prompt(role,topics,root=P,settings=None):
 paths=locations(root,settings)
 lock=json.loads(paths['skill_lock_file'].read_text());reg=json.loads(paths['registry_file'].read_text())
 files=release_files(root,settings)
 if set(files)!=set(lock['files']):raise ValueError('RELEASE_FILE_SET_CHANGED')
 for name,expected in lock['files'].items():
  if digest(files[name])!=expected:raise ValueError('RELEASE_CONTENT_CHANGED: '+name)
 if lock['release']!=reg['release']:raise ValueError('RELEASE_VERSION_MISMATCH')
 if role not in reg['roles']:raise ValueError('UNKNOWN_ROLE')
 if any(topic not in reg['role_allowed_topics'][role] for topic in topics):raise ValueError('TOPIC_NOT_ALLOWED')
 names=reg['base'][:]
 for topic in sorted(set(topics)):
  names.extend(reg['topics'][topic])
 names.append(reg['roles'][role]);names=list(dict.fromkeys(names))
 parts=[];loaded=[]
 for name in names:
  folder=paths['skills_root']/name;files=[folder/'SKILL.md']+sorted((folder/'references').glob('*'))
  for f in files:
   label='skills/'+str(f.relative_to(paths['skills_root']))
   content=f.read_text()
   if f.suffix=='.json':content=json.dumps(json.loads(content),ensure_ascii=False,separators=(',',':'))
   parts.append('['+label+']\n'+content);loaded.append(label)
 prompt='\n\n'.join(parts)
 if len(prompt)>reg['max_prompt_characters']:raise ValueError('PROMPT_BUDGET_EXCEEDED: choose narrower topics; do not silently truncate rules')
 return {'role':role,'release':lock['release'],'topics':sorted(set(topics)),'loaded_files':loaded,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'system_prompt':prompt,'model_profile':settings.model_profile(role) if settings else {'status':'RUNTIME_CONFIG_NOT_ATTACHED'},'config_hash':settings.config_hash if settings else None}

if __name__=='__main__':
 from config_loader import add_config_arguments,load_config,ConfigError
 parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['freeze','router','answer','judge']);parser.add_argument('--topics',default='');add_config_arguments(parser);a=parser.parse_args()
 try:
  settings=load_config(a.config,a.overlay)
  if a.operation=='freeze':print(json.dumps({'release':freeze(settings=settings)['release'],'status':'demo release locked'}))
  else:print(json.dumps(compile_prompt(a.operation,[x for x in a.topics.split(',') if x],settings=settings),ensure_ascii=False,indent=2))
 except (ConfigError,ValueError) as exc:parser.exit(2,str(exc)+'\n')
