"""Dispatch a validated plan to caller-provided adapters, without opening a DB.

The caller owns request classification, authentication and adapter registration.
This is not an LLM orchestration loop or a production authorization layer.
"""
from prompt_contracts import validate_output


def execute_plan(output, context, adapters):
    validate_output('router', output, context)
    plan = output['plan']
    if any(not callable(adapters.get(step['tool'])) for step in plan):
        raise ValueError('TOOL_ADAPTER_UNAVAILABLE')
    results = []
    for step in plan:
        results.append({'tool': step['tool'],
                        'result': adapters[step['tool']](**step['arguments'])})
    return results
