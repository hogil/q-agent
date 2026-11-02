"""Pure, deterministic knowledge-topic dependency resolution; no Tool authority."""


def resolve_topics(registry, role, topics, shared_topics=False):
    """Return a dependency-first list without mutating registry or input topics.

    Shared requests retain the compiler's online-union check followed by role
    filtering. Dependencies must still be available to the requested role.
    An invalid registry graph fails even when its broken edge is not requested.
    """
    if role not in registry['roles']:
        raise ValueError('UNKNOWN_ROLE')
    known = set(registry['topics'])
    allowed = set(registry['role_allowed_topics'][role])
    dependencies = registry.get('topic_dependencies', {})
    if not isinstance(dependencies, dict):
        raise ValueError('INVALID_TOPIC_DEPENDENCIES')
    for topic, values in dependencies.items():
        if topic not in known:
            raise ValueError('UNKNOWN_TOPIC_DEPENDENCY')
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError('INVALID_TOPIC_DEPENDENCIES')
        if any(value not in known for value in values):
            raise ValueError('UNKNOWN_TOPIC_DEPENDENCY')
    visiting, visited = set(), set()

    def validate(topic):
        if topic in visiting:
            raise ValueError('TOPIC_DEPENDENCY_CYCLE')
        if topic in visited:
            return
        visiting.add(topic)
        for dependency in sorted(set(dependencies.get(topic, []))):
            validate(dependency)
        visiting.remove(topic)
        visited.add(topic)

    for topic in sorted(known):
        validate(topic)
    requested = list(topics)
    if any(not isinstance(topic, str) or topic not in known for topic in requested):
        raise ValueError('TOPIC_NOT_ALLOWED')
    if shared_topics:
        online = set().union(*(set(values) for values in registry['role_allowed_topics'].values()))
        if any(topic not in online for topic in requested):
            raise ValueError('TOPIC_NOT_ALLOWED')
        requested = [topic for topic in requested if topic in allowed]
    elif any(topic not in allowed for topic in requested):
        raise ValueError('TOPIC_NOT_ALLOWED')
    resolved, loaded = [], set()

    def include(topic):
        if topic not in allowed:
            raise ValueError('TOPIC_DEPENDENCY_NOT_ALLOWED')
        if topic in loaded:
            return
        for dependency in sorted(set(dependencies.get(topic, []))):
            include(dependency)
        loaded.add(topic)
        resolved.append(topic)

    for topic in sorted(set(requested)):
        include(topic)
    return resolved
