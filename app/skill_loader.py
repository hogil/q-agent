"""Application-side Skill compiler. No model calls. Explicit freeze is a build step.
python skill_loader.py freeze
python skill_loader.py router --topics terminology,lots
"""
import argparse,json,hashlib
from pathlib import Path
from skill_graph import resolve_topics
P=Path(__file__).resolve().parent

def digest(path):
 # Released files are text; Git checkout line endings must not change identity.
 return hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
def locations(root,settings=None):
 if settings is None:return {'skills_root':root/'skills','dictionary_root':root/'domain-data','registry_file':root/'skill_registry.json','skill_lock_file':root/'release.lock.json'}
 return {key:Path(settings.data['paths'][key]) for key in ('skills_root','dictionary_root','registry_file','skill_lock_file')}
def release_files(root,settings=None):
 paths=locations(root,settings);files={}
 for label,key in [('skills','skills_root'),('domain-data','dictionary_root')]:
  if not paths[key].is_dir():raise ValueError('RELEASE_DIRECTORY_MISSING: '+key)
  for f in sorted(paths[key].rglob('*'),key=lambda f:f.relative_to(paths[key]).as_posix()):
   if f.is_file():files[label+'/'+f.relative_to(paths[key]).as_posix()]=f
 files['skill_registry.json']=paths['registry_file']
 for name in ['incident_tools.py','incident_statistics.py','incident_filters.py','terminology.py','prompt_contracts.py','skill_loader.py','config_loader.py','runtime_factory.py','run_agent.py','agent.py','action_scope_bridge.py','synthetic_sqlite_action_lease.py','synthetic_action_contract.py','llm_client.py','conversation_memory.py','evidence_review.py','document_evidence_contract.py','fbm_search_contract.py','mes_reference_contract.py','mes_reference_sqlite.py','meeting_tools.py','image_tools.py','engineering_tools.py','enterprise_tools.py','demo_data.py','engineering_demo.py','golden.py','platform_tools.py','platform_demo.py','platform_models.py','train_platform_models.py','column_profile.py','tabular_analysis.py','tabular_demo.py','map_analysis.py']:
  files[name]=root/name
 files['platform_facts.py']=root/'platform_facts.py'
 files['investigation_plans.py']=root/'investigation_plans.py'
 for name in ('skill_graph.py','context_manager.py','recovery_policy.py',
              'team_graph.py','team_ledger.py','team_executor.py','team_cli.py'):
  files[name]=root/name
 return files
def freeze(root=P,settings=None):
 # Explicit build operation; not called automatically by compile after changes.
 paths=locations(root,settings)
 manifest={'release':json.loads(paths['registry_file'].read_text(encoding='utf-8'))['release'],'files':{name:digest(f) for name,f in release_files(root,settings).items()}}
 paths['skill_lock_file'].write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');return manifest

def read_role_reference(role,filename,skills_root,registry_file):
 registry=json.loads(Path(registry_file).read_text(encoding='utf-8'))
 folder=registry['roles'][role]
 return json.loads((Path(skills_root)/folder/'references'/filename).read_text(encoding='utf-8'))

def compact_schema(document):
 columns=document['columns']
 if not columns:return document
 fields=list(next(iter(columns.values())))
 if any(set(value)!=set(fields) for value in columns.values()):return document
 return {**document,'column_fields':fields,
         'columns':{name:[value[field] for field in fields] for name,value in columns.items()}}

def compile_prompt(role,topics,root=P,settings=None,shared_topics=False,tool_names=None,include_schema_json=True,platform_review=False,context_phase='initial',omit_examples=False,omit_embedded_output_schema=False):
 paths=locations(root,settings)
 lock=json.loads(paths['skill_lock_file'].read_text(encoding='utf-8'));reg=json.loads(paths['registry_file'].read_text(encoding='utf-8'))
 files=release_files(root,settings)
 if set(files)!=set(lock['files']):raise ValueError('RELEASE_FILE_SET_CHANGED')
 for name,expected in lock['files'].items():
  if digest(files[name])!=expected:raise ValueError('RELEASE_CONTENT_CHANGED: '+name)
 if lock['release']!=reg['release']:raise ValueError('RELEASE_VERSION_MISMATCH')
 if context_phase not in ('initial','continuation','fallback','disabled'):raise ValueError('INVALID_CONTEXT_PHASE')
 if (omit_examples or omit_embedded_output_schema) and context_phase!='continuation':raise ValueError('CONTEXT_OMISSION_REQUIRES_CONTINUATION')
 requested_topics=list(topics)
 topics=resolve_topics(reg,role,requested_topics,shared_topics=shared_topics)
 requested_topics=sorted(set(requested_topics))
 names=reg['base'][:]
 for topic in topics:
  names.extend(reg['topics'][topic])
 names.append(reg['roles'][role]);names=list(dict.fromkeys(names))
 if platform_review and role in reg.get('platform_review_roles',{}):
  names=reg['platform_review_base']+[reg['platform_review_roles'][role]]
  topics=['platform']
 parts=[];loaded=[];entities=[]
 for name in names:
  folder=paths['skills_root']/name;files=[folder/'SKILL.md']+sorted((folder/'references').glob('*'))
  for f in files:
   if f.name=='investigation-recipes.json':continue
   if not include_schema_json and name.startswith('schema/') and f.suffix=='.json':continue
   if f.name=='examples.md' and (omit_examples or settings is None or not settings.data['runtime']['prompt_examples']):continue
   if f.name=='output.schema.json' and omit_embedded_output_schema:continue
   label='skills/'+f.relative_to(paths['skills_root']).as_posix()
   content=f.read_text(encoding='utf-8')
   if f.suffix=='.json':
    document=json.loads(content)
    if f.name=='tools.json' and tool_names is not None:
     document={key:value for key,value in document.items() if key in tool_names}
    if 'logical_sources' in document:
     document={**document,'logical_sources':{key:compact_schema(value) for key,value in document['logical_sources'].items()}}
    if f.name=='tools.json' and 'statistics' not in topics:
     document={name:({key:value for key,value in spec.items() if key!='parameters'} if name=='summarize_incidents' else spec)
               for name,spec in document.items()}
    if 'logical_entity' in document:
     entity=document['logical_entity']
     if settings and (entity not in settings.data['tables'] or set(document['columns'])!=set(settings.data['tables'][entity]['columns'])):
      raise ValueError('SCHEMA_MAPPING_MISMATCH: '+entity)
     entities.append(entity)
     document=compact_schema(document)
    content=json.dumps(document,ensure_ascii=False,separators=(',',':'))
   parts.append('['+label+']\n'+content);loaded.append(label)
 if settings and entities:
  # Only schema context belongs in model input, never connection credentials or paths.
  data=settings.data
  context={'dialect':data['database']['dialect'],'schema':data['database']['schema'],
           'tables':{entity:data['tables'][entity] for entity in sorted(set(entities))},
           'relations':data['relations'],'arrays':data['arrays']}
  parts.append('[runtime/schema-mapping]\nUse logical field names in Tool arguments. Empty physical column mappings are unavailable. Connection settings are managed by the Adapter.\n'+json.dumps(context,ensure_ascii=False,separators=(',',':')))
 prompt='\n\n'.join(parts)
 if len(prompt)>reg['max_prompt_characters']:raise ValueError(f'PROMPT_BUDGET_EXCEEDED: {role} {topics}: {len(prompt)} > {reg["max_prompt_characters"]}; choose narrower topics; do not silently truncate rules')
 return {'role':role,'release':lock['release'],'topics':sorted(set(topics)),'requested_topics':requested_topics,'dependency_order':topics,'context_phase':context_phase,'requires_transport_schema':bool(omit_embedded_output_schema),'available_topics':reg['role_allowed_topics'][role],'loaded_files':loaded,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'system_prompt':prompt,'model_profile':settings.model_profile(role) if settings else {'status':'RUNTIME_CONFIG_NOT_ATTACHED'},'config_hash':settings.config_hash if settings else None}

if __name__=='__main__':
 from config_loader import add_config_arguments,load_config,ConfigError
 parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['freeze','router','answer','judge']);parser.add_argument('--topics',default='');add_config_arguments(parser);a=parser.parse_args()
 try:
  settings=load_config(a.config,a.overlay)
  if a.operation=='freeze':print(json.dumps({'release':freeze(settings=settings)['release'],'status':'demo release locked'}))
  else:print(json.dumps(compile_prompt(a.operation,[x for x in a.topics.split(',') if x],settings=settings),ensure_ascii=False,indent=2))
 except (ConfigError,ValueError) as exc:parser.exit(2,str(exc)+'\n')
