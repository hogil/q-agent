"""Bounded, extractive chat memory. No extra LLM calls or generated facts."""
import json
import math
import re
import unicodedata


def _terms(text):
    text = unicodedata.normalize('NFC', text).casefold()
    text = re.sub(r'(?<=[a-z0-9])(?=[\uac00-\ud7a3])|(?<=[\uac00-\ud7a3])(?=[a-z0-9])', ' ', text)
    words = {word for word in re.findall(r'[^\W_]+(?:[-./][^\W_]+)*', text) if len(word) > 1 or word.isdigit()}
    # Hangul bigrams tolerate particles without a model-specific tokenizer.
    for word in re.findall(r'[\uac00-\ud7a3]{2,}', text):
        words.update(word[i:i + 2] for i in range(len(word) - 1))
    return words


def select_turns(messages, question, limits, include_answers=True):
    """Input is chronological and already restricted to an authorized room/incident."""
    turns = []
    for message in messages:
        if message['role'] == 'user':
            turns.append({'messages': [message], 'order': len(turns)})
        elif message['role'] == 'assistant' and include_answers and turns:
            turns[-1]['messages'].append(message)
    if not turns:
        return []
    recent = turns[-limits['recent_turns']:]
    older = turns[:-limits['recent_turns']]
    query = _terms(question)
    terms = [_terms(' '.join(m['content'] for m in turn['messages'])) for turn in turns]
    weights = {term: math.log(1 + len(turns) / (1 + sum(term in row for row in terms)))
               for term in query}
    ranked = sorted(older, key=lambda turn: (
        sum(weights[t] for t in query & terms[turn['order']]), turn['order']), reverse=True)
    recalled = [turn for turn in ranked if query & terms[turn['order']]][:limits['recalled_turns']]
    return [{**turn, 'selection': kind} for kind, group in
            (('recent', reversed(recent)), ('recalled', recalled)) for turn in group]


def _excerpt(text, question, length, focus):
    if len(text) <= length:
        return text, False
    start = 0
    if focus:
        terms = _terms(question)
        passages = list(re.finditer(r'[^\n.!?]+(?:[.!?]|$)', text))
        if passages:
            best = max(passages, key=lambda match: len(terms & _terms(match.group())))
            if terms & _terms(best.group()):
                start = max(0, best.start() - length // 4)
    end = min(len(text), start + length - 8)
    return ('... ' if start else '') + text[start:end] + (' ...' if end < len(text) else ''), True


def pack_turns(turns, question, budget):
    """Keep pairs together, prioritize recent turns, and cap serialized JSON characters."""
    accepted = []
    # Reserve room for metadata and multiple turns; this is characters, not tokens.
    per_message = min(1200, max(96, budget // 6))
    for turn in turns:
        rows = []
        for message in turn['messages']:
            content, truncated = _excerpt(message['content'], question, per_message,
                                          turn['selection'] == 'recalled')
            rows.append({'id': message['id'], 'turn_id': turn['messages'][0]['id'],
                         'role': message['role'], 'content': content, 'truncated': truncated,
                         'selection': turn['selection']})
        candidate = sorted([*accepted, (turn['order'], rows)], key=lambda item: item[0])
        flattened = [row for _, group in candidate for row in group]
        if len(json.dumps(flattened, ensure_ascii=False, separators=(',', ':'))) <= budget:
            accepted = candidate
    return [row for _, group in accepted for row in group]
