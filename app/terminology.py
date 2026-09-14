"""Deterministic terminology tool for labelled demo questions, not an LLM parser.

Dictionary matches are field-scoped and versioned. Fuzzy matches only propose
candidates. Source records are never rewritten by this module.
"""
import difflib
import json
import re
import unicodedata
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from incident_filters import fold


def match_values(question, values_by_field, max_candidates):
    """Return exact DB-value mentions, not automatically selected WHERE predicates."""
    text = ' '.join(unicodedata.normalize('NFKC', question).casefold().split())
    candidates = []
    particles = '에서|으로|부터|까지|에는|에서는|와|과|의|은|는|이|가|을|를|에|로|도|만'
    for field, values in values_by_field.items():
        for value in values:
            term = ' '.join(unicodedata.normalize('NFKC', value).casefold().split())
            if not term:
                continue
            pattern = r'(?<![\w-])' + re.escape(term) + r'(?:(?![\w-])|(?=(?:' + particles + r')(?![\w-])))'
            if re.search(pattern, text):
                candidates.append({'field': field, 'value': value, 'mention': term,
                                   'match': 'normalized_exact', 'ambiguous': False})
    occurrences = Counter(item['mention'] for item in candidates)
    for item in candidates:
        item['ambiguous'] = occurrences[item['mention']] > 1
    candidates.sort(key=lambda item: (-len(item['mention']), item['field'], item['value']))
    return {'candidates': candidates[:max_candidates], 'truncated': len(candidates) > max_candidates}


def load_dictionary(settings):
    data = json.loads(Path(settings.data['paths']['terminology_file']).read_text())
    if data.get('synthetic') and settings.data['environment'] not in ('demo', 'test'):
        raise ValueError('SYNTHETIC_DICTIONARY_NOT_ALLOWED_ONPREM')
    if not data.get('version') or not isinstance(data.get('fields'), dict):
        raise ValueError('INVALID_DICTIONARY')
    return data


def resolve(dictionary, field, raw, context, effective_at):
    values = dictionary['fields'][field].get('values', [])
    key = fold(raw)
    hits, rejected, suggestions = [], [], []
    for entry in values:
        names = ([entry['canonical']] if entry.get('canonical_match', True) else []) + entry.get('aliases', [])
        if key not in [fold(n) for n in names]:
            similarity = max((difflib.SequenceMatcher(None, key, fold(n)).ratio() for n in names), default=0)
            if similarity >= dictionary.get('candidate_threshold', .72):
                suggestions.append({'canonical': entry['canonical'], 'score': round(similarity, 3)})
            continue
        reason = None
        if entry.get('approved') is not True:
            reason = 'UNAPPROVED_ALIAS'
        elif entry.get('valid_from') and effective_at < entry['valid_from']:
            reason = 'ALIAS_NOT_YET_VALID'
        elif entry.get('valid_to') and effective_at >= entry['valid_to']:
            reason = 'EXPIRED_ALIAS'
        else:
            for name, expected in entry.get('scope', {}).items():
                if name not in context:
                    reason = 'SCOPE_CONTEXT_REQUIRED'; break
                if context[name] != expected:
                    reason = 'ALIAS_SCOPE_MISMATCH'; break
        record = {'canonical': entry['canonical'], 'source_id': entry['source_id'],
                  'scope': entry.get('scope', {}), 'reason': reason}
        (rejected if reason else hits).append(record)
    # Unresolved scoped candidates must not be silently defeated by a global alias.
    if any(r['reason'] == 'SCOPE_CONTEXT_REQUIRED' for r in rejected):
        return {'status': 'NEEDS_CLARIFICATION', 'reason': 'SCOPE_CONTEXT_REQUIRED', 'candidates': hits + rejected}
    distinct = {r['canonical'] for r in hits}
    if len(distinct) == 1:
        canonical = hits[0]['canonical']
        return {'status': 'RESOLVED', 'canonical': canonical,
                'method': 'canonical' if key == fold(canonical) else 'reviewed_alias', 'sources': hits}
    if len(distinct) > 1:
        return {'status': 'NEEDS_CLARIFICATION', 'reason': 'AMBIGUOUS_ALIAS', 'candidates': hits}
    if rejected:
        return {'status': 'NEEDS_CLARIFICATION', 'reason': rejected[0]['reason'], 'candidates': rejected}
    suggestions = sorted(suggestions, key=lambda r: (-r['score'], r['canonical']))[:5]
    return {'status': 'NEEDS_CLARIFICATION', 'reason': 'UNCONFIRMED_TYPO' if suggestions else 'UNKNOWN_TERM', 'candidates': suggestions}


def parse_fields(question, dictionary):
    """Finite labelled grammar: 도시=...; 부서=...; 요청=.... No free chat claim."""
    if not isinstance(question, str) or not question.strip() or len(question) > 12000:
        raise ValueError('INVALID_QUESTION')
    question = unicodedata.normalize('NFKC', question)
    labels = {}
    for name, spec in dictionary['fields'].items():
        for label in [name, *spec['labels']]:
            norm = fold(label)
            if norm in labels and labels[norm] != name:
                raise ValueError('AMBIGUOUS_DICTIONARY_FIELD')
            labels[norm] = name
    found, audit = {}, []
    for part in re.split(r'[;\n]', question):
        if not part.strip():
            continue
        bits = re.split(r'[:=]', part, maxsplit=1)
        if len(bits) != 2 or not bits[1].strip():
            raise ValueError('LABELLED_QUERY_REQUIRED')
        label, value = bits[0].strip(), bits[1].strip()
        logical = labels.get(fold(label))
        if logical is None:
            raise ValueError('UNKNOWN_FIELD: ' + label)
        if logical in found:
            raise ValueError('DUPLICATE_FIELD: ' + logical)
        found[logical] = value
        audit.append({'raw_label': label, 'logical_field': logical, 'raw_value': value})
    if not found:
        raise ValueError('EMPTY_QUERY')
    return found, audit


def month_range(raw, timezone):
    match = re.fullmatch(r'(\d{4})(?:년|[-/])(\d{1,2})월?', fold(raw))
    if not match:
        raise ValueError('EXPLICIT_YEAR_MONTH_REQUIRED')
    year, month = map(int, match.groups())
    start = datetime(year, month, 1, tzinfo=ZoneInfo(timezone))
    end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=start.tzinfo)
    return {'gte': start.isoformat(), 'lt': end.isoformat()}


def normalize_request(question, dictionary, timezone='Asia/Seoul', effective_at=None):
    result = {'raw_question': question, 'dictionary_version': dictionary['version'],
              'synthetic_dictionary': dictionary.get('synthetic', False),
              'effective_at': dictionary['as_of'] if effective_at is None else effective_at, 'audit': [], 'issues': [], 'filters': {}, 'request': 'incidents'}
    try:
        result['effective_at'] = date.fromisoformat(result['effective_at']).isoformat()
        raw, result['audit'] = parse_fields(question, dictionary)
    except (ValueError, TypeError) as exc:
        return {**result, 'status': 'INVALID_REQUEST', 'issues': [{'reason': str(exc)}]}
    context = {}
    modes = {'generation_mode': 'any', 'failure_mode': 'any'}
    def mapped(field, value):
        resolution = resolve(dictionary, field, value, context, result['effective_at'])
        result['audit'].append({'field': field, 'raw': value, **resolution})
        if resolution['status'] != 'RESOLVED':
            result['issues'].append({'field': field, 'raw': value, **resolution})
            return None
        return resolution['canonical']
    # Context is resolved before scoped aliases, independently of written order.
    ordered = ['city', 'line_code', 'line_alias', 'line', 'generation_mode', 'failure_mode', 'request']
    ordered += [field for field in raw if field not in ordered]
    for field in ordered:
        if field not in raw:
            continue
        value = raw[field]
        if field in ('incident_number', 'lot_id'):
            # Only case/width/space normalization: never repair O/0 or lost leading zeros.
            canonical = unicodedata.normalize('NFKC', value).strip().upper()
            pattern = r'SYN-\d{4}-\d{4}' if field == 'incident_number' else r'SYN-LOT-\d{4}-\d{3}'
            if not re.fullmatch(pattern, canonical):
                result['issues'].append({'field': field, 'reason': 'IDENTIFIER_REQUIRES_EXACT_FORMAT', 'raw': value}); continue
            if field == 'lot_id':
                result['lot_ids'] = [canonical]
            else:
                result['filters'][field] = canonical
        elif field == 'occurred_at':
            try:
                result['filters'][field] = month_range(value, timezone)
            except (ValueError, OverflowError):
                result['issues'].append({'field': field, 'reason': 'EXPLICIT_YEAR_MONTH_REQUIRED', 'raw': value})
        elif field in ('product_generations', 'fab_out_failure_codes'):
            parts = [s.strip() for s in unicodedata.normalize('NFKC', value).strip('{}[]').split(',')]
            if not all(parts):
                result['issues'].append({'field': field, 'reason': 'EMPTY_ARRAY_FILTER'}); continue
            resolved = [mapped(field, s) for s in parts]
            if all(v is not None for v in resolved):
                mode = modes['generation_mode' if field == 'product_generations' else 'failure_mode']
                result['filters'][field] = {'mode': mode, 'values': list(dict.fromkeys(resolved))}
        elif field == 'title_terms':
            terms = []
            for term in value.split('+'):
                if not term.strip():
                    result['issues'].append({'field': field, 'reason': 'EMPTY_TITLE_TERM'}); continue
                resolution = resolve(dictionary, field, term, context, result['effective_at'])
                if resolution['status'] == 'RESOLVED':
                    terms.append(resolution['canonical'])
                elif resolution['reason'] == 'UNKNOWN_TERM':
                    # Free title text remains a literal bound substring; never discard it.
                    terms.append(term.strip()); resolution['method'] = 'literal_title_term'
                else:
                    result['issues'].append({'field': field, 'raw': term, **resolution})
                result['audit'].append({'field': field, 'raw': term, **resolution})
            result['filters'][field] = terms
        else:
            canonical = mapped(field, value)
            if canonical is None:
                continue
            if field in modes:
                modes[field] = canonical
            elif field == 'request':
                result['request'] = canonical
            else:
                result['filters'][field] = canonical; context[field] = canonical
    for control, target in [('generation_mode', 'product_generations'), ('failure_mode', 'fab_out_failure_codes')]:
        if control in raw and target not in raw:
            result['issues'].append({'field': control, 'reason': 'ARRAY_MODE_WITHOUT_VALUES'})
    if result.get('lot_ids') and result['request'] != 'wafers':
        result['issues'].append({'field': 'lot_id', 'reason': 'LOT_FILTER_REQUIRES_WAFER_REQUEST'})
    if not result['filters']:
        result['issues'].append({'reason': 'INCIDENT_FILTER_REQUIRED'})
    result['status'] = 'NEEDS_CLARIFICATION' if result['issues'] else 'READY'
    return result
