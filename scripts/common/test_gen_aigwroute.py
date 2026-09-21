import pathlib
import unittest
from unittest.mock import patch
import gen_aigwroute as g


def service(name="frontend", port=8000):
    return {"metadata": {"name": name}, "spec": {
        "selector": {"nvidia.com/dynamo-component-type": "frontend"},
        "ports": [{"name": "http", "port": port}]}}


class DiscoveryTests(unittest.TestCase):
    def discover(self, inventory, ready=True, port=8000):
        slices = [{"metadata": {"labels": {"kubernetes.io/service-name": "frontend"}},
                   "endpoints": [{"conditions": {"ready": ready}}]}]
        with patch.object(g, "kubectl", side_effect=[
                {"items": [service(port=port)]}, {"items": slices}, inventory]) as call:
            models = g.discover_live("token-labs")
            return models, call.call_args_list

    def test_live_aliases_port_and_proxy(self):
        models, calls = self.discover({"data": [{"id": "org/one"}, {"id": "alias"}, {"id": "alias"}]}, port=8080)
        self.assertEqual([m.served_name for m in models], ["alias", "org/one"])
        self.assertEqual(models[0].backend_port, 8080)
        self.assertIsNone(models[0].selector)
        self.assertIn("http:frontend:8080/proxy/v1/models", calls[-1].args[2])
        rendered = g.render(models, "token-labs", pathlib.Path("/tmp/routes.yaml"))
        self.assertIn("port: 8080", rendered)
        self.assertNotIn("kind: Service\n", rendered)

    def test_null_endpoints_not_probed(self):
        with patch.object(g, "kubectl", side_effect=[
                {"items": [service()]}, {"items": [{"metadata": {}, "endpoints": None}]}]) as call:
            self.assertEqual(g.discover_live("token-labs"), [])
            self.assertEqual(call.call_count, 2)

    def test_unready_service_not_probed(self):
        models, calls = self.discover({}, ready=False)
        self.assertEqual(models, [])
        self.assertEqual(len(calls), 2)

    def test_invalid_or_empty_inventory_aborts(self):
        for inventory in [{}, {"data": []}, {"data": [{"id": None}]}, {"data": "bad"}]:
            with self.subTest(inventory=inventory), self.assertRaises(SystemExit):
                self.discover(inventory)

    def test_probe_failure_aborts(self):
        with patch.object(g, "kubectl", side_effect=[
                {"items": [service()]},
                {"items": [{"metadata": {"labels": {"kubernetes.io/service-name": "frontend"}},
                            "endpoints": [{"conditions": {"ready": True}}]}]},
                SystemExit("timeout")]):
            with self.assertRaises(SystemExit):
                g.discover_live("token-labs")

    def test_disaggregated_intent_deduplicates(self):
        def component(kind):
            return {"type": kind, "replicas": 1, "podTemplate": {"spec": {
                "containers": [{"args": ["--served-model-name", "org/model"]}]}}}
        obj = {"metadata": {"name": "disagg"}, "spec": {
            "components": [component("prefill"), component("decode")]}}
        with patch.object(g, "kubectl", return_value={"items": [obj]}):
            models = g.discover_dynamo("token-labs")
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].backend_host, "disagg-frontend.token-labs.svc.cluster.local")

    def test_live_apply_rejected_before_discovery(self):
        with patch("sys.argv", ["gen_aigwroute.py", "--discovery", "live", "--apply"]), patch.object(g, "kubectl") as call:
            with self.assertRaises(SystemExit):
                g.main()
            call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
