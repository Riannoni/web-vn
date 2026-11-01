"""No torch import/model/GPU: exercise actual device and summarize source with fakes."""
import ast
from contextlib import nullcontext
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SOURCE = (Path(__file__).resolve().parents[1] / 'worker' / 'vision_daemon.py').read_text()
TREE = ast.parse(SOURCE)


def functions():
    ns = {}
    nodes = [n for n in TREE.body if isinstance(n, ast.FunctionDef)
             and n.name in ('requested_vlm_device', 'summarize')]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<candidate>', 'exec'), ns)
    return ns


class VlmDevice(unittest.TestCase):
    def select(self, value, available):
        ns = functions()
        cuda = SimpleNamespace(is_available=Mock(return_value=available))
        ns.update(os=os, torch=SimpleNamespace(cuda=cuda))
        with patch.dict(os.environ, {}, clear=True):
            if value is not None:
                os.environ['VN_VLM_DEVICE'] = value
            result = ns['requested_vlm_device']()
        return result, cuda.is_available

    def test_default_cpu_does_not_probe_gpu(self):
        result, probe = self.select(None, False)
        self.assertEqual(result, 'cpu')
        probe.assert_not_called()

    def test_invalid_device_rejected(self):
        with self.assertRaisesRegex(ValueError, 'cpu or cuda'):
            self.select('auto', True)

    def test_requested_unavailable_cuda_is_not_silent_cpu_fallback(self):
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            self.select('cuda', False)

    def test_available_cuda_is_explicit(self):
        result, probe = self.select('cuda', True)
        self.assertEqual(result, 'cuda')
        probe.assert_called_once_with()

    def summarize(self, device):
        ns = functions()
        class Batch(dict):
            def to(self, destination):
                self.moved_to = destination
                return self
        batch = Batch(input_ids=SimpleNamespace(shape=(1, 3)), pixel_values=object())
        class Output:
            def __getitem__(self, key):
                return self
        output = Output()
        output.cpu = Mock(return_value=output)
        model = SimpleNamespace(generate=Mock(return_value=output))
        processor = SimpleNamespace(apply_chat_template=Mock(return_value=batch),
                                    batch_decode=Mock(return_value=[' caption ']))
        image = Mock()
        ns.update(VLM_DEVICE=device, vlm=model, vlm_processor=processor,
                  Image=SimpleNamespace(Resampling=SimpleNamespace(LANCZOS=1)),
                  torch=SimpleNamespace(inference_mode=nullcontext))
        self.assertEqual(ns['summarize'](image, 'same prompt'), 'caption')
        self.assertEqual(model.generate.call_args.kwargs['max_new_tokens'], 62)
        self.assertIs(model.generate.call_args.kwargs['do_sample'], False)
        self.assertEqual(model.generate.call_args.kwargs['repetition_penalty'], 1.15)
        return batch, output

    def test_cpu_summary_preserves_device_path(self):
        batch, output = self.summarize('cpu')
        self.assertFalse(hasattr(batch, 'moved_to'))
        output.cpu.assert_not_called()

    def test_cuda_moves_complete_batch_and_synchronizes_decode_on_cpu(self):
        batch, output = self.summarize('cuda')
        self.assertEqual(batch.moved_to, 'cuda')
        output.cpu.assert_called_once_with()

    def test_only_vlm_model_is_moved_and_dtype_attention_are_unchanged(self):
        move = [n for n in TREE.body if isinstance(n, ast.If)
                and 'VLM_DEVICE' in ast.unparse(n.test)]
        self.assertEqual(len(move), 1)
        for device in ('cpu', 'cuda'):
            model = Mock()
            ns = {'VLM_DEVICE': device, 'vlm': model}
            exec(compile(ast.Module(body=move, type_ignores=[]), '<placement>', 'exec'), ns)
            if device == 'cuda':
                model.to.assert_called_once_with('cuda')
            else:
                model.to.assert_not_called()
        self.assertIn('VLM_ID,dtype=torch.float32,attn_implementation="eager"', SOURCE)
        self.assertNotIn('clip.to(', SOURCE)


if __name__ == '__main__':
    unittest.main()
