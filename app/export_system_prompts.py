"""Export actual compiled system text with a source manifest."""
import argparse
import hashlib
import json
from pathlib import Path
from config_loader import add_config_arguments, load_config
from skill_loader import compile_prompt


def export(settings, target):
    target=Path(target);target.mkdir(parents=True,exist_ok=True)
    records=[]
    for role in ('router','judge','answer'):
        result=compile_prompt(role,['incident_search'],settings=settings)
        body=result['system_prompt'];filename=role+'.system.txt'
        (target/filename).write_text(body,encoding='utf-8')
        records.append({'file':filename,'role':role,'topics':result['topics'],'characters':len(body),
                        'sha256':hashlib.sha256(body.encode()).hexdigest(),'loaded_files':result['loaded_files']})
    manifest={'release':result['release'],'notice':'Actual compiler output for incident_search topic. Not a deployed model or model evaluation. Add Schema/terminology/Lot/document topics as needed by phase.',
              'role_contract_version':2,'configured_character_limit':json.loads(Path(settings.data['paths']['registry_file']).read_text())['max_prompt_characters'],'models_enabled':settings.data['models']['text']['enabled'],'prompts':records}
    (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);add_config_arguments(parser)
    parser.add_argument('--output');args=parser.parse_args();settings=load_config(args.config,args.overlay)
    print(json.dumps(export(settings,args.output or Path(settings.data['paths']['output_root'])/'system-prompts'),ensure_ascii=False,indent=2))
