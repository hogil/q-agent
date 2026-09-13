"""Incident-name resolution and separate Lot/Wafer table regression tests."""
import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

from check_config import ConfigTests
from generate_dummy import generate
from incident_tools import ToolError, ident
from runtime_factory import open_incident_tools


class WaferTests(unittest.TestCase):
    setUp = ConfigTests.setUp
    settings = ConfigTests.settings

    def fixture(self, override=None, filename='site.toml'):
        from config_loader import merge
        values = {'demo': {'incident_count': 4, 'lots_per_incident': 2, 'wafers_per_lot': 3},
                  'relations': {'source_completeness': 'declared_complete', 'wafer_source_completeness': 'declared_complete'}}
        settings = self.settings(merge(values, override or {}), filename)
        generate(settings)
        return settings

    def mutate(self, settings, sql, args=()):
        with closing(sqlite3.connect(settings.data['database']['sqlite_file'])) as db, db:
            db.execute(sql, args)

    def title(self, settings):
        with open_incident_tools(settings) as tool:
            return tool.find_incidents('u', incident_number='SYN-2026-0001')['data'][0]['title']

    def test_name_to_lots_to_wafers(self):
        s = self.fixture()
        title = self.title(s)
        with open_incident_tools(s) as tool:
            found = tool.find_incidents('u', title=title)
            lots = tool.list_incident_lots('u', found['scope_id'])
            wafers = tool.list_incident_wafers('u', found['scope_id'])
            self.assertEqual(lots['unique_lots'], 2)
            self.assertEqual(wafers['unique_wafers'], 6)
            self.assertEqual(wafers['status'], 'OK')
            self.assertTrue(all(row['title'] == title for row in wafers['items']))

    def test_duplicate_name_requires_explicit_selection(self):
        s = self.fixture(); title = self.title(s)
        self.mutate(s, 'UPDATE demo_incident SET accident_title=? WHERE accident_no=?', (title,'SYN-2026-0002'))
        with open_incident_tools(s) as tool:
            found = tool.find_incidents('u',title=title)
            self.assertEqual(found['status'],'NEEDS_SELECTION')
            with self.assertRaisesRegex(ToolError,'SELECTION_REQUIRED'):tool.list_incident_lots('u',found['scope_id'])
            with self.assertRaisesRegex(ToolError,'SELECTION_REQUIRED'):tool.list_incident_wafers('u',found['scope_id'])
            chosen = tool.select_incidents('u',found['scope_id'],['synthetic-pk-0002'])
            result = tool.list_incident_wafers('u',chosen['scope_id'])
            self.assertEqual({r['incident_number'] for r in result['items']},{'SYN-2026-0002'})
            with self.assertRaises(ToolError):tool.select_incidents('u',found['scope_id'],['synthetic-pk-0003'])

    def test_contains_is_literal_and_bound(self):
        s=self.fixture()
        self.mutate(s,'UPDATE demo_incident SET accident_title=? WHERE accident_no=?',('100%_Fail','SYN-2026-0001'))
        with open_incident_tools(s) as tool:
            found=tool.find_incidents('u',title='%_',title_match='contains')
            self.assertEqual(len(found['data']),1)
            self.assertEqual(tool.find_incidents('u',title="' OR 1=1 --",title_match='contains')['status'],'NO_MATCH')

    def test_full_pagination_preserves_every_composite_key(self):
        s=self.fixture({'runtime':{'default_page_size':2}})
        with open_incident_tools(s) as tool:
            found=tool.find_incidents('u',incident_number='SYN-2026-0001')
            rows=[];offset=0
            while True:
                page=tool.list_incident_wafers('u',found['scope_id'],offset=offset)
                rows+=page['items']
                if page['next_offset'] is None:break
                offset=page['next_offset']
            self.assertEqual(len(rows),6)
            self.assertEqual(len({(r['lot_id'],r['wafer_id']) for r in rows}),6)
            self.assertEqual(len({r['wafer_id'] for r in rows}),3)

    def test_shared_lot_does_not_mix_incident_wafer_memberships(self):
        s=self.fixture()
        self.mutate(s,'UPDATE demo_wafer_list SET wafer_no=? WHERE accident_ref=? AND lot_no=? AND wafer_no=?',
                    ('W99','synthetic-pk-0002','SYN-LOT-0001-001','W01'))
        with open_incident_tools(s) as tool:
            first=tool.find_incidents('u',incident_number='SYN-2026-0001')
            rows=tool.list_incident_wafers('u',first['scope_id'])['items']
            self.assertNotIn('W99',{r['wafer_id'] for r in rows})
            second=tool.find_incidents('u',incident_number='SYN-2026-0002')
            rows=tool.list_incident_wafers('u',second['scope_id'])['items']
            self.assertIn('W99',{r['wafer_id'] for r in rows})

    def test_lot_filter_is_limited_to_selected_incident(self):
        s=self.fixture()
        with open_incident_tools(s) as tool:
            scope=tool.find_incidents('u',incident_number='SYN-2026-0001')['scope_id']
            with self.assertRaisesRegex(ToolError,'OUTSIDE'):tool.list_incident_wafers('u',scope,lot_ids=['SYN-LOT-0003-001'])
            page=tool.list_incident_wafers('u',scope,lot_ids=['SYN-LOT-0001-002'])
            self.assertEqual(page['total_memberships'],3)
            self.assertIsNone(page['coverage'][0]['expected_wafers'])
            self.assertEqual(page['coverage'][0]['state'],'unknown_expected_count')

    def test_missing_wafer_rows_are_not_reported_as_normal(self):
        s=self.fixture()
        self.mutate(s,'DELETE FROM demo_wafer_list WHERE accident_ref=? AND lot_no=?',('synthetic-pk-0001','SYN-LOT-0001-002'))
        with open_incident_tools(s) as tool:
            scope=tool.find_incidents('u',incident_number='SYN-2026-0001')['scope_id']
            page=tool.list_incident_wafers('u',scope)
            self.assertEqual(page['status'],'PARTIAL')
            self.assertEqual(page['coverage'][0]['state'],'count_mismatch')
            self.assertEqual(page['lots_without_wafer_rows'],[{'incident_id':'synthetic-pk-0001','lot_id':'SYN-LOT-0001-002'}])

    def test_zero_wafer_rows_preserve_count_mismatch(self):
        s=self.fixture()
        self.mutate(s,'DELETE FROM demo_wafer_list WHERE accident_ref=?',('synthetic-pk-0001',))
        with open_incident_tools(s) as tool:
            scope=tool.find_incidents('u',incident_number='SYN-2026-0001')['scope_id']
            page=tool.list_incident_wafers('u',scope)
            self.assertEqual(page['total_memberships'],0)
            self.assertEqual(page['status'],'PARTIAL')

    def test_duplicate_rows_deduplicate_and_conflicts_fail(self):
        s=self.fixture()
        self.mutate(s,'INSERT INTO demo_wafer_list SELECT * FROM demo_wafer_list LIMIT 1')
        with open_incident_tools(s) as tool:
            scope=tool.find_incidents('u',incident_number='SYN-2026-0001')['scope_id']
            self.assertEqual(tool.list_incident_wafers('u',scope)['total_memberships'],6)
        self.mutate(s,'INSERT INTO demo_wafer_list VALUES (?,?,?,?)',('synthetic-pk-0001','SYN-LOT-0001-001','W01','CONFLICT'))
        with open_incident_tools(s) as tool:
            scope=tool.find_incidents('u',incident_number='SYN-2026-0001')['scope_id']
            with self.assertRaisesRegex(ToolError,'CONFLICTING'):tool.list_incident_wafers('u',scope)

    def test_inventory_scope_does_not_claim_incident_impact(self):
        s=self.fixture({'relations':{'wafer_scope':'lot_inventory'},'tables':{'wafer_list':{'columns':{'incident_ref':''}}}})
        with open_incident_tools(s) as tool:
            scope=tool.find_incidents('u',incident_number='SYN-2026-0001')['scope_id']
            page=tool.list_incident_wafers('u',scope)
            self.assertEqual(page['wafer_scope'],'lot_inventory')
            self.assertEqual(page['coverage'][0]['state'],'inventory_not_incident_impact')
            self.assertIsNone(page['coverage'][0]['expected_wafers'])
            self.assertEqual(page['unique_wafers'],6)

    def test_actual_title_join_and_duplicate_title_rejection(self):
        s=self.fixture({'relations':{'incident_parent_key':'title','wafer_parent_key':'title'}})
        title=self.title(s)
        with open_incident_tools(s) as tool:
            scope=tool.find_incidents('u',title=title)['scope_id']
            self.assertEqual(tool.list_incident_wafers('u',scope)['total_memberships'],6)
        self.mutate(s,'UPDATE demo_incident SET accident_title=? WHERE accident_no=?',(title,'SYN-2026-0002'))
        with self.assertRaisesRegex(ToolError,'NON_UNIQUE_PARENT_KEY'):
            with open_incident_tools(s):pass

    def test_all_table_and_column_renames_preserve_wafer_results(self):
        a=self.fixture()
        tables={name:{'name':'테이블_'+str(n),'columns':{key:'컬럼_'+str(i) for i,key in enumerate(table['columns'])}}
                for n,(name,table) in enumerate(a.data['tables'].items())}
        b=self.fixture({'tables':tables,'paths':{'data_root':str(self.root/'renamed'),'output_root':str(self.root/'renamed-out')}},'renamed.toml')
        results=[]
        for s in (a,b):
            with open_incident_tools(s) as tool:
                scope=tool.find_incidents('u',title=self.title(s))['scope_id']
                results.append(tool.list_incident_wafers('u',scope)['items'])
        self.assertEqual(results[0],results[1])

    def test_lot_and_wafer_can_reference_different_incident_keys(self):
        s=self.fixture({'relations':{'incident_parent_key':'title','wafer_parent_key':'incident_number'}})
        with open_incident_tools(s) as tool:
            scope=tool.find_incidents('u',title=self.title(s))['scope_id']
            self.assertEqual(tool.list_incident_wafers('u',scope)['unique_wafers'],6)

    def test_scope_owner_expiry_and_missing_scope(self):
        s=self.fixture()
        with open_incident_tools(s) as tool:
            with self.assertRaises(ToolError):tool.list_incident_wafers('u','missing')
            scope=tool.find_incidents('u',incident_number='SYN-2026-0001')['scope_id']
            with self.assertRaises(ToolError):tool.list_incident_wafers('other',scope)
            tool.scopes[scope]['expires_at']=0
            with self.assertRaises(ToolError):tool.list_incident_wafers('u',scope)

    def test_no_incident_match_is_not_a_wafer_list(self):
        s=self.fixture()
        with open_incident_tools(s) as tool:
            scope=tool.find_incidents('u',title='등록되지 않은 가상 사고')['scope_id']
            page=tool.list_incident_wafers('u',scope)
            self.assertEqual(page['status'],'NO_MATCH')
            self.assertEqual(page['items'],[])


if __name__=='__main__':
    # ConfigTests supplies helpers, but is not an additional suite here.
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(WaferTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
