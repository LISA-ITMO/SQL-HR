"""Reranker loading and ordering contracts; no network or real model in unit tests."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'agent_server/reranker.py'
MODEL = 'cross-encoder/mmarco-mMiniLMv2-L12-H384-v1'


class RerankerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / 'model'
        self.downloads = []

        def download(repo_id, local_dir, allow_patterns):
            self.downloads.append(repo_id)
            self.seed(Path(local_dir))

        class LocalEncoder:
            def __init__(encoder, path, max_length, local_files_only=False):
                if not (Path(path) / 'config.json').is_file():
                    raise FileNotFoundError('Local model was not prepared')
                encoder.max_length = max_length

            def predict(encoder, pairs):
                return [-2.0, 4.0, 1.0][:len(pairs)]

        self.env = patch.dict(os.environ, {
            'ENABLE_RERANKING': 'True', 'CROSS_ENCODER_CACHE_DIR': str(self.cache),
            'RERANKER_MAX_LENGTH': '512',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop('RERANKER_MODEL', None)
        modules = {
            'sentence_transformers': types.SimpleNamespace(CrossEncoder=LocalEncoder),
            'huggingface_hub': types.SimpleNamespace(snapshot_download=download),
        }
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('reranker_under_test', SOURCE)
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.candidates = [{'id': 'unrelated'}, {'id': 'best'}, {'id': 'partial'}]

    @staticmethod
    def seed(path):
        path.mkdir(parents=True, exist_ok=True)
        (path / 'config.json').write_text(json.dumps({'model_type': 'xlm-roberta'}))
        (path / 'model.safetensors').write_bytes(b'unit-test-weights')
        (path / 'tokenizer.json').write_text('{}')

    def test_downloads_default_multilingual_model_into_empty_cache(self):
        reranker = self.module.CandidateReranker()
        self.assertTrue(reranker._enabled)
        self.assertEqual(self.downloads, [MODEL])
        self.assertEqual(reranker._model.max_length, 512)

    def test_complete_local_model_loads_without_download(self):
        self.seed(self.cache)
        reranker = self.module.CandidateReranker()
        self.assertTrue(reranker._enabled)
        self.assertEqual(self.downloads, [])
        self.assertEqual([c['id'] for c in reranker.rerank_candidates('запрос', self.candidates, 2)], ['best', 'partial'])

    def test_scores_remain_descending_and_top_k_is_applied(self):
        self.seed(self.cache)
        result = self.module.CandidateReranker().rerank_with_scores('запрос', self.candidates, 2)
        self.assertEqual([(c['id'], float(score)) for c, score in result], [('best', 4.0), ('partial', 1.0)])

    def test_explicit_model_override_still_works(self):
        os.environ['RERANKER_MODEL'] = 'cross-encoder/ms-marco-MiniLM-L-6-v2'
        self.module.CandidateReranker()
        self.assertEqual(self.downloads, ['cross-encoder/ms-marco-MiniLM-L-6-v2'])

    def test_disabled_reranker_does_not_download(self):
        os.environ['ENABLE_RERANKING'] = 'False'
        reranker = self.module.CandidateReranker()
        self.assertEqual(reranker.rerank_candidates('запрос', self.candidates, 2), self.candidates[:2])
        self.assertEqual(self.downloads, [])

    def test_empty_query_keeps_input_order(self):
        self.seed(self.cache)
        reranker = self.module.CandidateReranker()
        self.assertEqual(reranker.rerank_with_scores(' ', self.candidates, 2), [(c, 0.0) for c in self.candidates[:2]])


@unittest.skipUnless(os.getenv('RERANKER_TEST_MODEL_DIR'), 'Set RERANKER_TEST_MODEL_DIR for offline real-model checks')
class RealModelTests(unittest.TestCase):
    def test_russian_queries_rank_relevant_profile_first(self):
        import functools
        import math
        import torch

        torch.set_num_threads(4)
        with patch.dict(os.environ, {
            'ENABLE_RERANKING': 'True', 'RERANKER_MODEL': MODEL, 'RERANKER_MAX_LENGTH': '512',
            'CROSS_ENCODER_CACHE_DIR': os.environ['RERANKER_TEST_MODEL_DIR'],
            'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'TOKENIZERS_PARALLELISM': 'false',
        }):
            spec = importlib.util.spec_from_file_location('real_reranker_under_test', SOURCE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.CrossEncoder = functools.partial(module.CrossEncoder, device='cpu')
            reranker = module.CandidateReranker()
            self.assertTrue(reranker._enabled)
            self.assertIsNotNone(reranker._model)
            candidates = [
                {'id': 'python', 'work_text': 'Программист Python: разработка API на FastAPI, PostgreSQL, SQL, автоматизация обработки данных.'},
                {'id': 'legal', 'work_text': 'Юрист: судебное представительство, подготовка исков, договорное право, сопровождение судебных споров.'},
                {'id': 'nurse', 'work_text': 'Медицинская сестра: уход за пациентами, выполнение назначений врача, внутривенные инъекции.'},
            ]
            cases = [
                ('legal', 'Нужен юрист с опытом судебного представительства и договорной работы'),
                ('python', 'Ищем программиста Python для разработки API и работы с PostgreSQL'),
                ('nurse', 'Нужна медицинская сестра с опытом ухода за пациентами и выполнения инъекций'),
            ]
            for expected, query in cases:
                with self.subTest(query=query):
                    ranked = reranker.rerank_with_scores(query, candidates, 3)
                    self.assertEqual(ranked[0][0]['id'], expected)
                    scores = [float(score) for _, score in ranked]
                    self.assertTrue(all(math.isfinite(score) for score in scores))
                    self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == '__main__':
    unittest.main()
