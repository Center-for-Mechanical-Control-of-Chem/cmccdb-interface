"""Advanced Search predicates and SQL relationship regression tests.

Run from cmccdb-interface with the normal schema/runtime environment.
The small SQL execution fixtures use SQLite; PostgreSQL-specific ANY/ALL and
unnest predicates are also checked as generated SQL, without a live database.
"""
import json
import sqlite3
import unittest
from pathlib import Path
from cmccdb_schema.proto import reaction_pb2
from cmccdb_interface.database.query import SchemaQueryFragment as Fragment, AdvancedSearchQuery as Query, Selectors
ROOT = Path(__file__).resolve().parents[1]

class SearchTests(unittest.TestCase):
    def test_all_numeric_comparators_include_boundaries(self):
        expected = {'==': '=', '!=': '<>', '<': '<', '>': '>', '<=': '<=', '>=': '>='}
        for operator, sql in expected.items():
            fragment = Fragment.from_path(['OutcomesList', 0, 'ReactionTime', 'Value'], operator + ' 1e2')
            self.assertEqual(fragment.val, 100.0)
            self.assertEqual(fragment.selector_templates[fragment.selector], '{query_value} ' + sql + ' %s')

    def test_decimal_negative_exponent_and_zero(self):
        for text, expected in [('0', 0), ('-.25', -.25), ('+1.', 1), ('1e-3', .001)]:
            self.assertEqual(Fragment.parse_val(text, float)[0], expected)

    def test_range_parameter_count_and_reverse_rejection(self):
        for operator in ['in range', 'not in range']:
            item = Fragment.from_path(['OutcomesList', 0, 'ReactionTime', 'Value'], operator + ' [1, 2]')
            self.assertEqual(item.parameters(), [1., 2.])
            self.assertIn('BETWEEN %s AND %s', item.selector_templates[item.selector])
        with self.assertRaises(ValueError):
            Fragment.parse_val('in range [2, 1]', float)

    def test_contains_keeps_spaces_punctuation_and_doi(self):
        self.assertEqual(Fragment.parse_val('contains ball-milling at 25 °C', str),
                         ('ball-milling at 25 °C', Selectors.Contains))
        self.assertEqual(Fragment.parse_val('does not contain 10.1039/d3mr00025g', str)[0], '10.1039/d3mr00025g')
        self.assertEqual(Fragment.parse_val('10.1039/d3mr00025g', str)[0], '10.1039/d3mr00025g')

    def test_none_of_uses_all(self):
        item = Fragment.from_path(['DatasetID'], 'none of [cmcc-a, cmcc-b]')
        self.assertEqual(item.val, ['cmcc-a', 'cmcc-b'])
        self.assertEqual(item.selector_templates[item.selector], '{query_value} <> ALL(%s)')

    def test_enum_numeric_named_and_list(self):
        path = ['OutcomesList', 0, 'ProductsList', 0, 'MeasurementsList', 0, 'Type', 'allowedValues']
        yield_id = reaction_pb2.ProductMeasurement.YIELD
        self.assertEqual(Fragment.from_path(path, yield_id).val, 'YIELD')
        self.assertEqual(Fragment.from_path(path, 'YIELD').val, 'YIELD')
        membership = Fragment.from_path(path, 'any of [YIELD, PURITY]')
        self.assertEqual(membership.val, ['YIELD', 'PURITY'])
        self.assertEqual(membership.predicate('measurement'), 'CAST(measurement.type AS text) = ANY(%s)')
        with self.assertRaises(ValueError):
            Fragment.from_path(path, 99999)

    def test_false_and_zero_are_typed(self):
        self.assertIs(Fragment.from_path(['Provenance', 'IsMined'], False).val, False)
        self.assertIs(Fragment.from_path(['Provenance', 'IsMined'], 'false').val, False)
        self.assertEqual(Fragment.from_path(['OutcomesList', 0, 'ReactionTime', 'Value'], 0).val, 0.)

    def test_malformed_requests_and_leaf_names_are_rejected(self):
        for payload in [None, [], {}, {'Conditions': {}}, {'ReactionId;SELECT': 'x'}, {'NoSuchField': 'x'},
                        {'ReactionId': {'NoSuchField': 'x'}}, {'ReactionId': None}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                Query.from_json(payload)
        for text in ['>= x', '<= 2oops', 'in range [1]', 'any of []', 'none of [1,]', 'NaN', 'inf']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                Fragment.parse_val(text, float)

    def test_integer_and_boolean_type_rejection(self):
        for value, dtype in [('2.5', int), (True, int), ('false', float), ('no', bool), ('> true', bool)]:
            with self.assertRaises(ValueError):
                Fragment.parse_val(value, dtype)

    def test_field_count_and_depth_limits(self):
        with self.assertRaises(ValueError):
            Query.from_json({'ReactionId': ['x'] * 129})
        body = 'x'
        for _ in range(34):
            body = {'Field': body}
        with self.assertRaises(ValueError):
            Query.from_json(body)

    def test_repeated_scalars_use_unnest_and_negative_membership_is_universal(self):
        for text, negative in [('contains screw', False), ('none of [steel, screw]', True)]:
            query = Query.from_json({'Conditions': {'Mechanochemistry': {'GeometryList': [text]}}})
            statement, parameters = query._statement()
            self.assertIn('unnest(', statement)
            self.assertEqual('NOT EXISTS' in statement, negative)
            self.assertEqual(statement.count('%s'), len(parameters))
        with self.assertRaises(ValueError):
            Query.from_json({'ReactionId': ['invalid list on scalar']})

    def test_every_editable_generated_field_resolves_against_real_descriptors(self):
        metadata = ROOT.parent / 'cmccdb-schema/js/cmccdb-schema/reaction_pb.json'
        if not metadata.is_file():
            self.skipTest('Schema metadata requires the sibling cmccdb-schema source checkout')
        tree = json.loads(metadata.read_text())
        count = 0
        def visit(node, path):
            nonlocal count
            if isinstance(node, dict) and 'allowedValues' in node:
                Fragment.from_path(path + ['allowedValues'], next(iter(node['allowedValues'].values())))
                count += 1
            elif isinstance(node, dict):
                for key, child in node.items():
                    visit(child, path + [key] + ([0] if key.endswith(('Map', 'List')) else []))
            elif node != 'ByteArray':
                Fragment.from_path(path, {'float': '1.2', 'int': '1', 'bool': False, 'string': 'test'}[node])
                count += 1
        visit(tree, [])
        self.assertGreater(count, 500)

    def fixture(self):
        connection = sqlite3.connect(':memory:')
        connection.execute("ATTACH DATABASE ':memory:' AS cmccdb")
        connection.executescript('''
          CREATE TABLE cmccdb.dataset (id INTEGER, dataset_id TEXT);
          CREATE TABLE cmccdb.reaction (id INTEGER, dataset_id INTEGER, reaction_id TEXT, proto BLOB);
          CREATE TABLE cmccdb.reaction_outcome (id INTEGER, reaction_id INTEGER, cmccdb_schema_context TEXT);
          CREATE TABLE cmccdb.product_compound (id INTEGER, reaction_outcome_id INTEGER, cmccdb_schema_context TEXT);
          CREATE TABLE cmccdb.product_measurement (id INTEGER, product_compound_id INTEGER, type TEXT, cmccdb_schema_context TEXT);
          CREATE TABLE cmccdb.percentage (id INTEGER, product_measurement_id INTEGER, value REAL, cmccdb_schema_context TEXT);
          INSERT INTO cmccdb.dataset VALUES (1, 'dataset-fixture');
        ''')
        for rid, measurements in [(1, [('YIELD', 20), ('PURITY', 95)]), (2, [('YIELD', 80), ('PURITY', 10)])]:
            connection.execute('INSERT INTO cmccdb.reaction VALUES (?,1,?,?)', (rid, 'r' + str(rid), b'proto'))
            connection.execute("INSERT INTO cmccdb.reaction_outcome VALUES (?,?,'Reaction.outcomes')", (rid, rid))
            connection.execute("INSERT INTO cmccdb.product_compound VALUES (?,?,'ReactionOutcome.products')", (rid, rid))
            for number, (kind, value) in enumerate(measurements):
                mid = rid * 10 + number
                connection.execute("INSERT INTO cmccdb.product_measurement VALUES (?,?,?,'ProductCompound.measurements')", (mid, rid, kind))
                connection.execute("INSERT INTO cmccdb.percentage VALUES (?,?,?,'ProductMeasurement.percentage')", (mid, mid, value))
        return connection

    def test_real_sql_does_not_cross_match_measurements(self):
        query = Query.from_json({'OutcomesList': [{'ProductsList': [{'MeasurementsList': [
            {'Type': {'allowedValues': reaction_pb2.ProductMeasurement.YIELD}, 'Percentage': {'Value': '>=70'}}]}]}]})
        statement, parameters = query._statement()
        self.assertEqual(statement.count('%s'), len(parameters))
        connection = self.fixture()
        try:
            rows = connection.execute(statement.replace('%s', '?'), parameters).fetchall()
            self.assertEqual([row[1] for row in rows], ['r2'])
            connection.execute("UPDATE cmccdb.percentage SET cmccdb_schema_context='OtherContext.percentage' WHERE product_measurement_id=20")
            self.assertEqual(connection.execute(statement.replace('%s', '?'), parameters).fetchall(), [])
        finally:
            connection.close()

    def test_repeated_entries_use_separate_aliases(self):
        query = Query.from_json({'OutcomesList': [{'ProductsList': [{'MeasurementsList': [
            {'Type': {'allowedValues': 'YIELD'}, 'Percentage': {'Value': '>=70'}},
            {'Type': {'allowedValues': 'PURITY'}, 'Percentage': {'Value': '<=20'}}]}]}]})
        statement, parameters = query._statement()
        self.assertEqual(statement.count('JOIN cmccdb.product_measurement AS'), 2)
        connection = self.fixture()
        try:
            self.assertEqual([row[1] for row in connection.execute(statement.replace('%s', '?'), parameters)], ['r2'])
        finally:
            connection.close()

    def test_range_executes_with_correct_values(self):
        query = Query.from_json({'OutcomesList': [{'ProductsList': [{'MeasurementsList': [
            {'Type': {'allowedValues': 'YIELD'}, 'Percentage': {'Value': 'not in range [25, 75]'}}]}]}]})
        statement, parameters = query._statement()
        connection = self.fixture()
        try:
            self.assertEqual([row[1] for row in connection.execute(statement.replace('%s', '?'), parameters)], ['r1', 'r2'])
        finally:
            connection.close()



class EndpointTests(unittest.TestCase):
    def setUp(self):
        import flask
        from unittest.mock import patch
        from cmccdb_interface.client import search
        app = flask.Flask(__name__)
        app.register_blueprint(search.bp)
        self.client = app.test_client()
        patcher = patch.object(search.query, 'run_query', return_value=[])
        self.run_query = patcher.start()
        self.addCleanup(patcher.stop)

    def test_limits_and_database_are_forwarded(self):
        for argument, expected in [('', 1000), ('&limit=10', 10), ('&limit=99999', 1000)]:
            response = self.client.post('/client/api/advanced-query?database=staging' + argument,
                                        json={'ReactionId': 'fixture'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.run_query.call_args.kwargs['limit'], expected)
            self.assertEqual(self.run_query.call_args.kwargs['database_name'], 'staging')

    def test_invalid_input_is_json_and_never_queries(self):
        for argument in ['0', '-1', '1.5', '', 'bad']:
            response = self.client.post('/client/api/advanced-query?limit=' + argument,
                                        json={'ReactionId': 'fixture'})
            self.assertEqual(response.status_code, 400)
            self.assertIn('message', response.get_json())
        for body in ['invalid JSON', 'null', '[]', '{}']:
            response = self.client.post('/client/api/advanced-query', data=body, content_type='application/json')
            self.assertEqual(response.status_code, 400)
        self.run_query.assert_not_called()

    def test_server_errors_are_logged_and_hide_private_details(self):
        self.run_query.side_effect = RuntimeError('private database details')
        with self.assertLogs(level='ERROR'):
            response = self.client.post('/client/api/advanced-query', json={'ReactionId': 'fixture'})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('private', response.get_json()['message'])
        self.assertNotIn('traceback', response.get_json())
        self.assertTrue(response.get_json()['request_id'])


if __name__ == '__main__':
    unittest.main()
