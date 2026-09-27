"""Completeness and fill-only rules for author-owned future planning."""


def _json(node):
    return node.model_dump(mode='json', by_alias=True) if hasattr(node, 'model_dump') else node


def apply_completion_patch(before, patch):
    """Overlay omissions with authoritative values; reject unknown/changed fields."""
    from copy import deepcopy
    def overlay(old, new):
        if isinstance(old, dict) and isinstance(new, dict):
            if set(new) - set(old): raise ValueError('completion contains unknown fields')
            return {key: overlay(value, new[key]) if key in new else deepcopy(value) for key,value in old.items()}
        if isinstance(old, (list, tuple)) and old and isinstance(new, (list, tuple)):
            if len(old)!=len(new): raise ValueError('completion cannot reorder or resize existing lists')
            return [overlay(a,b) for a,b in zip(old,new)]
        return deepcopy(new)
    result=overlay(_json(before),patch)
    merge_missing_node(before,result)
    return result


def completion_patch_schema(node, schema, definitions):
    """Only missing content is model-owned; identity and filled text are excluded."""
    from copy import deepcopy
    protected={'id','clientNodeKey','revision','contentHash','order','lifecycle','volumeRef','plotRefs'}
    value=_json(node)
    if '$ref' in schema: schema=definitions[schema['$ref'].split('/')[-1]]
    properties={}
    for key,old in value.items():
        if key in protected: continue
        field=schema.get('properties',{}).get(key,{})
        if isinstance(old,str) and not old.strip(): properties[key]=deepcopy(field)
        elif isinstance(old,(list,tuple)):
            if not old: properties[key]=deepcopy(field)
            elif all(isinstance(item,dict) for item in old):
                children=[completion_patch_schema(item,field.get('items',{}),definitions) for item in old]
                if any(child['properties'] for child in children):
                    properties[key]={'type':'array','prefixItems':children,'items':False,'minItems':len(old),'maxItems':len(old)}
    return {'type':'object','properties':properties,'additionalProperties':False}


def missing_volume_fields(node):
    value = _json(node)
    return [label for key, label in [('title', '卷名称'), ('coreChange', '本卷核心变化'),
                                    ('mainPressure', '本卷主要压力')]
            if not str(value.get(key, '')).strip()]


def missing_block_fields(node):
    value = _json(node)
    missing = [label for key, label in [('title', '故事块名称'), ('blockGoal', '故事块目标')]
               if not str(value.get(key, '')).strip()]
    stages = [s for s in value.get('stages', []) if s.get('lifecycle', 'active') == 'active']
    if not stages:
        missing.append('阶段与场景任务')
    for index, stage in enumerate(stages, 1):
        for key, label in [('title', '名称'), ('purpose', '目的'), ('dramaticQuestion', '戏剧问题')]:
            if not str(stage.get(key, '')).strip(): missing.append(f'阶段 {index}：{label}')
        tasks = [t for t in stage.get('sceneTasks', []) if t.get('lifecycle', 'active') == 'active']
        if not tasks: missing.append(f'阶段 {index}：场景任务')
        for number, task in enumerate(tasks, 1):
            if any(not str(task.get(key, '')).strip() for key in ['task', 'completionEvidence']):
                missing.append(f'阶段 {index} / 任务 {number}：任务内容或完成依据')
    return missing


def merge_missing_node(before, after):
    """Reject any overwrite; populated lists cannot be extended or reordered.

    Only an empty list or blank text can be filled. Identity, relations, lifecycle
    and ordering are never fillable, even when their value is null.
    """
    protected = {'id', 'clientNodeKey', 'revision', 'contentHash', 'order', 'lifecycle', 'volumeRef', 'plotRefs'}

    def walk(old, new, key=''):
        if key in protected:
            if old != new: raise ValueError('completion must preserve identity and relations')
        elif isinstance(old, dict):
            if not isinstance(new, dict) or old.keys() != new.keys():
                raise ValueError('completion must preserve node shape')
            for field in old: walk(old[field], new[field], field)
        elif isinstance(old, (list, tuple)):
            if not isinstance(new, (list, tuple)):
                raise ValueError('completion requires a list')
            if old:
                if len(old) != len(new): raise ValueError('completion cannot add to populated lists')
                for a, b in zip(old, new): walk(a, b)
        elif isinstance(old, str) and not old.strip():
            if not isinstance(new, str): raise ValueError('completion requires text')
        elif old != new:
            raise ValueError('completion must preserve populated fields')

    walk(_json(before), _json(after))
    return after
