"""GUI lifecycle regressions. Run under xvfb-run when no display is available."""
import os
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import tkinter as tk
import whisper_gui as gui

@unittest.skipUnless(os.environ.get('DISPLAY'), 'requires a display (use xvfb-run)')
class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        with patch.object(gui.WhisperMMVGUI, '_startup_check', lambda self: None):
            self.app = gui.WhisperMMVGUI(self.root)
        self.root.update()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
    def tearDown(self):
        self.app._busy = False
        self.app.on_closing()
        self.assertEqual(self.errors, [])
    def spin(self, condition, timeout=3):
        until=time.monotonic()+timeout
        while not condition() and time.monotonic()<until:
            self.root.update();time.sleep(.005)
        self.root.update()
        self.assertTrue(condition())
    def test_minimum_layout_and_readonly_documents(self):
        self.root.geometry('980x680');self.root.update()
        for name in ['select_btn','kill_btn','digest_btn','export_btn','engine_l_btn']:
            w=getattr(self.app,name)
            self.assertTrue(w.winfo_ismapped(),name)
            self.assertLessEqual(w.winfo_rooty()+w.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height(),name)
        self.assertEqual(self.app.fmt_textbox.cget('state'),'disabled')
    def test_worker_updates_are_queued_and_bounded(self):
        seen=[]
        worker=threading.Thread(target=lambda:[self.app.ui(lambda:seen.append(threading.get_ident())) for _ in range(600)])
        worker.start();worker.join()
        self.assertEqual(seen,[])
        self.app._drain_events()
        self.assertEqual(len(seen),128)
        self.spin(lambda:len(seen)==600)
        self.assertEqual(set(seen),{threading.get_ident()})
    def test_stop_does_not_start_second_worker_or_enable_next_job(self):
        reached=threading.Event();events=[];app=self.app
        class Model:
            def transcribe(self,*args,**kwargs):
                print('Detected language: English')
                reached.set()
                app.kill_flag.wait(2)
                print('[00:00.000 --> 00:02.000] Completed words only')
                raise AssertionError('must stop at the completed boundary')
        def post(text,segments,path):
            events.append(('post',text))
            self.assertEqual(events[0],('release',None))
            self.assertTrue(app._busy)
            app.ui(lambda:app._set_processing(False))
        app._set_processing(True)
        with patch.object(gui,'get_best_gpu',return_value=None),patch.object(gui.whisper,'load_model',return_value=Model()),patch.object(app,'_release_whisper_model',side_effect=lambda:events.append(('release',None))),patch.object(app,'run_postprocess',side_effect=post):
            worker=threading.Thread(target=app.run_whisper,args=('fixture.wav',));worker.start()
            self.spin(reached.is_set)
            app.kill_whisper()
            self.assertIsNone(app.post_thread)
            self.assertEqual(str(app.select_btn.cget('state')),'disabled')
            self.spin(lambda:not worker.is_alive());worker.join()
            self.spin(lambda:not app._busy)
        self.assertEqual(events,[('release',None),('post','Completed words only')])
        self.assertEqual(app.last_language,'en')
    def test_stop_before_first_text_recovers_to_idle(self):
        self.app._set_processing(True);self.app.kill_whisper()
        with patch.object(gui,'get_best_gpu',return_value=None),patch.object(gui.whisper,'load_model') as load,patch.object(self.app,'run_postprocess') as post:
            worker=threading.Thread(target=self.app.run_whisper,args=('unused.wav',));worker.start()
            self.spin(lambda:not worker.is_alive());worker.join();self.spin(lambda:not self.app._busy)
            load.assert_not_called();post.assert_not_called()
        self.assertEqual(str(self.app.select_btn.cget('state')),'normal')
    def test_export_current_tab_utf8_and_busy_shortcut_guard(self):
        with TemporaryDirectory() as d:
            dest=Path(d)/'transcript.txt';self.app.last_result={'formatted':'原文です。'}
            self.app._set_textbox(self.app.fmt_textbox,'原文です。')
            with patch.object(gui.filedialog,'asksaveasfilename',return_value=str(dest)):
                self.app.export_text()
            self.assertEqual(dest.read_text(),'原文です。')
            self.app._set_processing(True)
            with patch.object(gui.filedialog,'askopenfilename') as chooser:
                self.app.select_file();chooser.assert_not_called()
    def test_options_are_snapshotted_and_no_worker_tk_reads(self):
        app=self.app;app.opt_minutes.set(False);app._job_settings=app._snapshot_options()
        app.opt_minutes.set(True)
        with patch.object(app.opt_minutes,'get',side_effect=AssertionError('worker Tk access')),patch.object(app.opt_speaker,'get',side_effect=AssertionError('worker Tk access')),patch.object(app.opt_fidelity,'get',side_effect=AssertionError('worker Tk access')),patch.object(gui,'mmv_formatting',return_value=('words.',[('words','words.',False)])),patch.object(gui,'gpu_info_str',return_value='test GPU'),patch.object(gui,'mmv_minutes') as notes:
            worker=threading.Thread(target=app.run_postprocess,args=('words',None,'fixture.wav'));worker.start()
            self.spin(lambda:not worker.is_alive());worker.join();self.spin(lambda:app.last_result is not None)
            notes.assert_not_called()
    def test_error_status_survives_deferred_exception_scope(self):
        with patch.object(gui,'get_best_gpu',side_effect=RuntimeError('fixture failure')):
            self.app._set_processing(True)
            worker=threading.Thread(target=self.app.run_whisper,args=('unused.wav',));worker.start()
            self.spin(lambda:not worker.is_alive());worker.join();self.spin(lambda:not self.app._busy)
        self.assertIn('fixture failure',self.app.status_var.get())
    def test_cloud_and_download_consent_remain_required(self):
        if gui.MMV_L:
            self.app.engine_var.set('L')
            with patch.object(gui.messagebox,'askokcancel',return_value=False) as consent:
                self.app._confirm_cloud_engine();consent.assert_called_once()
            self.assertEqual(self.app.engine_var.get(),'M')
        with patch.object(gui.filedialog,'askopenfilename',return_value='/not-used.wav'),patch.object(gui,'whisper_weights_path',return_value='/not-present.pt'),patch.object(gui.messagebox,'askokcancel',return_value=False) as consent,patch.object(gui.threading,'Thread') as worker:
            self.app.select_file();consent.assert_called_once();worker.assert_not_called()

class ResourceTests(unittest.TestCase):
    def test_free_memory_counts_other_processes(self):
        with patch.object(gui.torch.cuda,'is_available',return_value=True),patch.object(gui.torch.cuda,'mem_get_info',return_value=(3*1024**3,16*1024**3)) as mem:
            self.assertEqual(gui.get_free_vram_gb(1),3);mem.assert_called_once_with(1)
    def test_vram_wait_can_stop(self):
        event=threading.Event();event.set()
        with patch.object(gui,'get_free_vram_gb',return_value=0):
            with self.assertRaises(gui.TranscriptionStopped):gui.wait_for_vram(0,7,30,lambda _:None,event)
if __name__=='__main__':unittest.main()
