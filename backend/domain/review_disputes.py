"""Author-authored dispute history; never modifies a quality report."""
from hashlib import sha256
import json
from collections.abc import Mapping

SOURCES = ('candidate', 'canon', 'planning', 'outline', 'contract', 'bible')
CATEGORIES = ('attribution', 'state_change', 'custody', 'style', 'other')


def evidence_catalogue(candidate, snapshot):
    records = []
    def walk(value, path, source):
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, path + '/' + str(key).replace('~', '~0').replace('/', '~1'), source)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(item, path + '/' + str(index), source)
        elif isinstance(value, str) and value.strip():
            digest = sha256(value.encode()).hexdigest()
            identity = sha256(json.dumps([source, path, digest], ensure_ascii=False).encode()).hexdigest()
            records.append({'id': identity, 'sourceType': source, 'sourcePointer': path,
                            'text': value, 'textHash': digest})
    walk(candidate['content'], '/content', 'candidate')
    for source in SOURCES[1:]:
        walk(snapshot.get(source + '_context', {}), '', source)
    return records


def validate_history(events, report, revision):
    if not isinstance(events, (list, tuple)) or len(events) > 512:
        raise ValueError('invalid dispute history')
    findings = {f['id']: f for f in (report or {}).get('findings', [])}
    seen = set(); last_revision = 0; active = {}
    for event in events:
        if not isinstance(event, Mapping) or set(event) != {'id', 'revision', 'findingId', 'action', 'category', 'reason', 'evidence', 'createdAt'}:
            raise ValueError('invalid dispute event')
        if (not isinstance(event['id'], str) or len(event['id']) != 64 or any(c not in '0123456789abcdef' for c in event['id'])
            or event['id'] in seen or type(event['revision']) is not int
            or not last_revision < event['revision'] <= revision
            or event['findingId'] not in findings or event['action'] not in ('note', 'retain', 'revoke')
            or event['category'] not in CATEGORIES or not isinstance(event['reason'], str)
            or not 1 <= len(event['reason'].strip()) <= 2000
            or type(event['createdAt']) is not int or event['createdAt'] < 0
            or not isinstance(event['evidence'], (list, tuple)) or len(event['evidence']) > 8):
            raise ValueError('invalid dispute event values')
        if event['action'] == 'retain':
            previous = active.get(event['findingId'])
            if (findings[event['findingId']].get('severity') != 'required' or not event['evidence']
                or not previous or previous['action'] != 'note'
                or any(event[k] != previous[k] for k in ('reason', 'category', 'evidence'))):
                raise ValueError('retain requires saved required dispute and evidence')
        if event['action'] == 'revoke' and event['findingId'] not in active:
            raise ValueError('nothing to revoke')
        for ref in event['evidence']:
            if (not isinstance(ref, Mapping) or set(ref) != {'id', 'sourceType', 'sourcePointer', 'text', 'textHash', 'quote'}
                or ref['sourceType'] not in SOURCES or not isinstance(ref['sourcePointer'], str)
                or not isinstance(ref['text'], str) or not isinstance(ref['quote'], str)
                or not ref['quote'].strip() or ref['quote'] not in ref['text']
                or sha256(ref['text'].encode()).hexdigest() != ref['textHash']
                or sha256(json.dumps([ref['sourceType'], ref['sourcePointer'], ref['textHash']], ensure_ascii=False).encode()).hexdigest() != ref['id']):
                raise ValueError('invalid dispute evidence')
        seen.add(event['id']); last_revision = event['revision']; active[event['findingId']] = event
    return active


def retained_ids(report, decisions):
    decisions = decisions or {}
    active = validate_history(decisions.get('disputeEvents', []), report, decisions.get('revision', 0))
    return {key for key, event in active.items() if event['action'] == 'retain'}
