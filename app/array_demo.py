"""Existing product-generation arrays: SQLite JSON semantic demo, not a production adapter."""
import json
import sqlite3


def run():
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE incidents (id TEXT PRIMARY KEY, generations TEXT, wafers INTEGER)')
    rows = [('A', ['D1a', 'D1z', 'D1a'], 120), ('B', ['D1a'], 80),
            ('C', ['D20'], 20), ('D', [], 5), ('E', None, None)]
    db.executemany('INSERT INTO incidents VALUES (?,?,?)',
                   [(key, json.dumps(gens) if gens is not None else None, n) for key, gens, n in rows])

    def find(generation):
        return [r[0] for r in db.execute('''
            SELECT i.id FROM incidents i
            WHERE EXISTS (SELECT 1 FROM json_each(i.generations) g WHERE g.value = ?)
            ORDER BY i.id''', (generation,))]

    counts = dict(db.execute('''
        SELECT g.value, COUNT(DISTINCT i.id)
        FROM incidents i, json_each(i.generations) g
        GROUP BY g.value ORDER BY g.value'''))
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    check('exact membership', find('D1a') == ['A', 'B'])
    check('no partial matching', find('D1') == [])
    check('parameter binding', find("D1a' OR 1=1 --") == [])
    check('deduplicate within each incident', counts == {'D1a': 2, 'D1z': 1, 'D20': 1})
    check('multi-generation totals differ from distinct population', sum(counts.values()) == 4)
    check('unknown and empty arrays retained', db.execute(
        'SELECT COUNT(*) FROM incidents WHERE generations IS NULL OR json_array_length(generations)=0'
    ).fetchone()[0] == 2)
    check('incident quantities not duplicated by expansion', db.execute(
        'SELECT SUM(wafers) FROM incidents').fetchone()[0] == 225)
    result = {'notice': '합성 데이터. 세대별 수량 배분 정보가 없어 세대별 Wafer 수 계산 불가.',
              'tests': len(checks), 'generation_incident_counts': counts,
              'unique_incidents': 5, 'missing_generation_incidents': 2,
              'incidents_with_generation': 3, 'sum_of_generation_memberships': 4}
    db.close()
    return result


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False))
