import unittest
from unittest.mock import MagicMock, patch
from disaster_crawler.tls import tls_context


class TLSTests(unittest.TestCase):
    def test_missing_default_roots_use_maintained_bundle(self):
        context = MagicMock()
        context.get_ca_certs.return_value = []
        with patch.dict('os.environ', {}, clear=True), patch('disaster_crawler.tls.ssl.create_default_context', return_value=context), patch('certifi.where', return_value='/maintained/ca.pem'):
            self.assertIs(tls_context(), context)
        context.load_verify_locations.assert_called_once_with(cafile='/maintained/ca.pem')

    def test_explicit_trust_and_populated_default_are_preserved(self):
        for roots, env in [([{'issuer': 'existing'}], {}), ([], {'SSL_CERT_FILE': '/operator/ca.pem'}), ([], {'SSL_CERT_DIR': '/operator/roots'})]:
            context = MagicMock()
            context.get_ca_certs.return_value = roots
            with patch.dict('os.environ', env, clear=True), patch('disaster_crawler.tls.ssl.create_default_context', return_value=context):
                self.assertIs(tls_context(), context)
            context.load_verify_locations.assert_not_called()
