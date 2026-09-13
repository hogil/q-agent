"""Application-side Skill compiler. No model calls. Explicit freeze is a build step.
python skill_loader.py freeze
python skill_loader.py router --topics terminology,lots
"""
import argparse,json,hashlib
from pathlib import Path
P=Path(__file__).resolve().parent

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def release_files(root):
 files=list((root/'skills').rglob('*'))+list((root/'domain-data').rglob('*'))
 files += [root/n for n in ['skill_registry.json','mapping.example.json','rag_sources.example.json','incident_tools.py','skill_loader.py']]
 return sorted(f for f in files if f.is_file())
def freeze(root=P):
 # Explicit build operation; not called automatically by compile after changes.
 manifest={'release':json.loads((root/'skill_registry.json').read_text())['release'],'files':{str(f.relative_to(root)):digest(f) for f in release_files(root)}}
 (root/'release.lock.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));return manifest

def compile_prompt(role,topics,root=P):
 lock=json.loads((root/'release.lock.json').read_text());reg=json.loads((root/'skill_registry.json').read_text())
 files={str(f.relative_to(root)) for f in release_files(root)}
 if files!=set(lock['files']):raise ValueError('RELEASE_FILE_SET_CHANGED')
 for name,expected in lock['files'].items():
  if digest(root/name)!=expected:raise ValueError('RELEASE_CONTENT_CHANGED: '+name)
 if lock['release']!=reg['release']:raise ValueError('RELEASE_VERSION_MISMATCH')
 if role not in reg['roles']:raise ValueError('UNKNOWN_ROLE')
 if any(topic not in reg['role_allowed_topics'][role] for topic in topics):raise ValueError('TOPIC_NOT_ALLOWED')
 names=reg['base'][:]
 for topic in sorted(set(topics)):
  names.extend(reg['topics'][topic])
 names.append(reg['roles'][role]);names=list(dict.fromkeys(names))
 parts=[];loaded=[]
 for name in names:
  folder=root/'skills'/name;files=[folder/'SKILL.md']+sorted((folder/'references').glob('*'))
  for f in files:
   content=f.read_text();parts.append('['+str(f.relative_to(root))+']\n'+content);loaded.append(str(f.relative_to(root)))
 prompt='\n\n'.join(parts)
 if len(prompt)>reg['max_prompt_characters']:raise ValueError('PROMPT_BUDGET_EXCEEDED: choose narrower topics; do not silently truncate rules')
 return {'role':role,'release':lock['release'],'topics':sorted(set(topics)),'loaded_files':loaded,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'system_prompt':prompt,'model_profile':reg['model_profile'][role]}

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['freeze','router','answer','judge']);parser.add_argument('--topics',default='');a=parser.parse_args()
 if a.operation=='freeze':print(json.dumps({'release':freeze()['release'],'status':'demo release locked'}))
 else:print(json.dumps(compile_prompt(a.operation,[x for x in a.topics.split(',') if x]),ensure_ascii=False,indent=2))
