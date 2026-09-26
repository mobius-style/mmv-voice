import unittest
from unittest.mock import patch
from types import SimpleNamespace
import whisper_gui as gui

class GPUProbeTests(unittest.TestCase):
    def test_failed_device_does_not_break_status_or_hide_healthy_device(self):
        with patch.object(gui.torch.cuda, 'is_available', return_value=True), patch.object(gui.torch.cuda, 'device_count', return_value=2), patch.object(gui, 'get_free_vram_gb', side_effect=[8.0, RuntimeError('device unavailable')]):
            self.assertEqual(gui.get_best_gpu(), 0)
        with patch.object(gui.torch.cuda, 'is_available', return_value=True), patch.object(gui.torch.cuda, 'device_count', return_value=2), patch.object(gui.torch.cuda, 'get_device_properties', side_effect=[SimpleNamespace(name='healthy', total_memory=16*1024**3), RuntimeError('device unavailable')]), patch.object(gui, 'get_free_vram_gb', return_value=8.0):
            status=gui.gpu_info_str()
            self.assertIn('healthy',status)
            self.assertIn('GPU1: unavailable',status)
        with patch.object(gui.torch.cuda, 'is_available', return_value=True), patch.object(gui.torch.cuda, 'device_count', return_value=1), patch.object(gui, 'get_free_vram_gb', side_effect=RuntimeError('CUDA init failed')):
            self.assertIsNone(gui.get_best_gpu())
