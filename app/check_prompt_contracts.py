"""Check authored role examples and reject invalid control flow. No model calls."""
import copy
import json
from pathlib import Path
from prompt_contracts import validate_output

ROOT=Path(__file__).resolve().parent
examples=json.loads((ROOT/'data/prompt_contract_examples.json').read_text())['cases']
by_id={c['id']:c for c in examples}
checks=[]
for case in examples:
    validate_output(case['role'],case['expected_output'],case['context'])
    checks.append({'name':case['id']+' authored example conforms','passed':True})


def rejects(name,id,mutate):
    case=copy.deepcopy(by_id[id]);mutate(case['expected_output'],case['context'])
    try:validate_output(case['role'],case['expected_output'],case['context'])
    except ValueError:checks.append({'name':name,'passed':True});return
    raise AssertionError(name)


rejects('unavailable hybrid is blocked','R03',lambda o,c:c['available_tools']['search_incident_text'].update(enabled=False))
rejects('post-incident tools require scope','R05',lambda o,c:c.update(scope_valid=False))
rejects('tool cannot cross incident gate','R01',lambda o,c:c['available_tools']['find_incidents'].update(stage='tools'))
rejects('forward/self dependency forbidden','R01',lambda o,c:o['plan'][0].update(depends_on=[0]))
rejects('negative dependency forbidden','R01',lambda o,c:o['plan'][0].update(depends_on=[-1]))
rejects('undefined EDS field rejected','R03',lambda o,c:o['plan'][0]['arguments'].update(fields=['eds_failure_detail']))
rejects('SQL cannot be relabelled hybrid','R01',lambda o,c:o.update(search_mode='hybrid'))
rejects('blocked response must explain','R04',lambda o,c:o.update(limitations=[]))
rejects('clarification needs question','R06',lambda o,c:o.update(clarification=None))
rejects('budget enforced','R01',lambda o,c:c.update(budget_remaining=0))
rejects('no Judge handoff before DB check','R07',lambda o,c:c.update(incident_checked=False))
rejects('judge return goes to top router','J01',lambda o,c:o.update(return_to='answer'))
rejects('code FAIL cannot become pass','J04',lambda o,c:c.update(code_gate='FAIL'))
rejects('missing requirement cannot pass','J04',lambda o,c:o['coverage'][0].update(status='missing'))
rejects('missing requirement not omitted','J04',lambda o,c:o.update(coverage=[]))
rejects('Judge cannot invent evidence','J04',lambda o,c:o['coverage'][0].update(evidence_ids=['invented']))
rejects('no endless retrieval without budget','J01',lambda o,c:c.update(budget_remaining=0))
rejects('Answer follows Judge','A01',lambda o,c:c.update(judge_verdict='need_evidence'))
rejects('Answer cannot invent citation','A01',lambda o,c:o['claims'][0].update(evidence_ids=['invented']))
rejects('unknown output key rejected','A01',lambda o,c:o.update(missing_evidence=[]))
rejects('partial answer must expose limitation','A02',lambda o,c:o.update(limitations=[]))
rejects('duplicate claim IDs rejected','A01',lambda o,c:o['claims'].append(copy.deepcopy(o['claims'][0])))
rejects('pass cannot retain unresolved issues','J04',lambda o,c:o['issues'].append({'type':'conflict','reason':'Unresolved quantity conflict','next_action':'Compare source versions','evidence_ids':[]}))
rejects('answered cannot omit factual claims','A01',lambda o,c:o.update(claims=[]))
rejects('partial cannot omit factual claims','A02',lambda o,c:o.update(claims=[]))
rejects('blank answer is not a usable response','A01',lambda o,c:o.update(answer='   '))
rejects('blank claim is not evidence-backed communication','A01',lambda o,c:o['claims'][0].update(text=' '))
rejects('blank limitation does not explain uncertainty','A02',lambda o,c:o.update(limitations=[' ']))
rejects('blank clarification does not resolve ambiguity','R06',lambda o,c:o.update(clarification=' '))
print(json.dumps({'notice':'Authored schema/control-flow checks, not LLM quality evaluation.', 'checks':len(checks),'authored_examples':len(examples),'rejection_cases':len(checks)-len(examples),'passed':True},ensure_ascii=False))
