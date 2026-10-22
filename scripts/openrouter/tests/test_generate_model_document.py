import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    'model_document', Path(__file__).parents[1] / 'generate_model_document.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class ModelDocumentTests(unittest.TestCase):
    def args(self, *options):
        return generator.argument_parser().parse_args([
            '--schema', '/tmp/schema.json', '--output', '/tmp/models.json',
            '--concurrency', '1', *options])

    def test_free_flint_preserves_backend_identity_and_openrouter_mapping(self):
        document = generator.build_document(self.args(
            '--free', '--model-id', 'RecursiveSI/flint',
            '--openrouter-slug', 'recursive/flint-v1.0',
            '--hf-model-id', 'RecursiveSI/flint', '--name', 'Recursive: Flint',
            '--quantization', 'nvfp4'))
        self.assertEqual(document['id'], 'RecursiveSI/flint')
        self.assertEqual(document['hugging_face_id'], 'RecursiveSI/flint')
        self.assertEqual(document['openrouter']['slug'], 'recursive/flint-v1.0')
        self.assertEqual(document['quantization'], 'nvfp4')
        self.assertTrue(document['is_free'])
        self.assertFalse(document['is_ready'])
        self.assertNotIn('datacenters', document)
        for direction in ('input_modalities', 'output_modalities'):
            self.assertNotIn('pricing', document[direction][0])
            self.assertNotIn('capacity', document[direction][0])

    def test_paid_metadata_preserves_explicit_prices_and_measured_capacity(self):
        document = generator.build_document(self.args(
            '--prompt-price', '0.000001', '--completion-price', '0.000002',
            '--prompt-tpm', '100', '--completion-tpm', '50',
            '--requests-per-minute', '10'))
        self.assertFalse(document['is_free'])
        self.assertEqual(document['input_modalities'][0]['pricing'][0]['cost_usd'],
                         '0.000001')
        self.assertEqual(document['input_modalities'][0]['capacity'][0]['value'], 100)
        self.assertEqual(document['capacity'][0]['value'], 10)


if __name__ == '__main__':
    unittest.main()
