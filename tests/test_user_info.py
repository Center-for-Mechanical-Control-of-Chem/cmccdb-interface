"""The HTTP user-info endpoint serializes anonymous and cached users as JSON."""
import unittest
from unittest.mock import patch

import flask
from cmccdb_interface.client import authentication


class UserInfoTests(unittest.TestCase):
    def setUp(self):
        app = flask.Flask(__name__)
        app.secret_key = 'synthetic-test-session-key'
        app.register_blueprint(authentication.bp)
        self.app = app
        self.client = app.test_client()

    def test_anonymous_http_response_is_json_null(self):
        with patch.object(authentication, 'gh_user_email_data') as remote:
            response = self.client.get('/client/api/user-info')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_json)
        self.assertIsNone(response.get_json())
        remote.assert_not_called()

    def test_internal_anonymous_helper_retains_none(self):
        with self.app.test_request_context('/'):
            self.assertIsNone(authentication.gh_get_cache_user_info())

    def test_cached_user_keeps_the_existing_json_fields(self):
        with self.client.session_transaction() as session:
            session.update(github_email='fixture@example.invalid', github_username='fixture',
                           github_name='Synthetic fixture', github_cmcc_status=False,
                           github_cmcc_owner=False)
        with patch.object(authentication, 'gh_user_email_data') as remote:
            response = self.client.get('/client/api/user-info')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'email': 'fixture@example.invalid',
            'username': 'fixture', 'name': 'Synthetic fixture', 'member': False, 'owner': False})
        remote.assert_not_called()


if __name__ == '__main__':
    unittest.main()
