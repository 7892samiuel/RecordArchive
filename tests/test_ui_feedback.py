import importlib.util
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
ui=load('feedback_test',ROOT/'share-import/ui_feedback.py')
backend=load('backend_feedback_test',ROOT/'share-import/shared_record_backend.py')
support=load('support_test',ROOT/'share-import/support_diagnostics.py')

class Root:
    def __init__(self):self.callbacks=[]
    def after(self,delay,callback):self.callbacks.append(callback);return 'timer'
    def deiconify(self):pass
    def lift(self):pass

class Application:
    def __init__(self):
        self.owner=threading.get_ident();self.busy=False;self.root=Root();self.text='';self.editor=None
        self.status=SimpleNamespace(set=self.set_text)
        self.share_timer=None;self.share_events=None;self.loaded=[]
    def poll_share(self):ui.poll_share(self)
    def task(self,*args,**kwargs):return ui.task(self,*args,**kwargs)
    def load_record(self,data):self.loaded.append(data)
    def set_text(self,text):
        if threading.get_ident()!=self.owner:raise AssertionError('Tk state touched from worker')
        self.text=text
    def set_busy(self,value):
        if threading.get_ident()!=self.owner:raise AssertionError('Tk controls touched from worker')
        self.busy=value
    def finish(self):
        deadline=time.monotonic()+2
        while self.busy and time.monotonic()<deadline:
            callback=self.root.callbacks.pop(0);callback();time.sleep(.001)
        if self.busy:raise AssertionError('UI task did not finish')

class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.log=[]
        self.patch=patch.dict('sys.modules',{'support_diagnostics':SimpleNamespace(
            record=lambda *a,**k:self.log.append(a),record_error=lambda *a:self.log.append(a))})
        self.patch.start()
    def tearDown(self):self.patch.stop()

    def test_worker_progress_and_completion_only_touch_ui_thread(self):
        app=Application();result=[]
        def work(progress):progress('reading');return threading.get_ident()
        ui.task(app,work,result.append);app.finish()
        self.assertNotEqual(result[0],app.owner)
        self.assertEqual(app.text,'reading')

    def test_worker_failure_restores_controls_and_calls_error_handler(self):
        app=Application();errors=[]
        def work(progress):raise ValueError('read failed')
        ui.task(app,work,lambda result:None,errors.append);app.finish()
        self.assertEqual(errors,['read failed']);self.assertFalse(app.busy)

    def test_finish_exception_is_visible_instead_of_silent_callback_failure(self):
        app=Application();errors=[]
        def finish(result):raise RuntimeError('preview failed')
        ui.task(app,lambda progress:1,finish,errors.append);app.finish()
        self.assertIn('RuntimeError',errors[0]);self.assertFalse(app.busy)

    def test_pending_archive_is_consumed_once_even_if_notification_was_lost(self):
        app=Application();reads=[]
        app.read_page=lambda:self.fail('A share notification must not invoke the page reader')
        def shared():reads.append('share');return {'title':'分享测试'}
        with patch.dict('sys.modules',{'shared_record_backend':SimpleNamespace(
            pending_batch_id=lambda:'a'*32,read_pending=shared)}):
            ui.poll_share(app);app.finish();ui.poll_share(app)
        self.assertEqual(reads,['share']);self.assertEqual(app.loaded,[{'title':'分享测试'}])

    def test_stale_share_notification_does_not_read_a_different_open_page(self):
        app=Application();app.share_events=SimpleNamespace(take=lambda:True)
        app.read_page=lambda:self.fail('No shared batch exists')
        with patch.dict('sys.modules',{'shared_record_backend':SimpleNamespace(
            pending_batch_id=lambda:None,read_pending=lambda:self.fail('No shared batch exists'))}):
            ui.poll_share(app)
        self.assertFalse(app.busy);self.assertEqual(app.loaded,[])

    def test_retry_share_button_does_not_read_an_open_window_when_no_batch_exists(self):
        app=Application()
        with patch.dict('sys.modules',{'shared_record_backend':SimpleNamespace(read_pending=lambda:None),
                'page_capture':None,'direct_page':None,'visual_page':None}):
            ui.receive_share(app);app.finish()
        self.assertEqual(app.loaded,[])
        self.assertIn('暂无待接收',app.text)

    def test_retry_share_button_loads_only_forwarded_content(self):
        app=Application()
        with patch.dict('sys.modules',{'shared_record_backend':SimpleNamespace(read_pending=lambda:{'title':'分享测试'}),
                'page_capture':None,'direct_page':None,'visual_page':None}):
            ui.receive_share(app);app.finish()
        self.assertEqual(app.loaded,[{'title':'分享测试'}])

    def test_startup_never_guides_users_to_page_reading(self):
        app=Application();app.data={'messages':[]}
        import os
        with patch.dict(os.environ,{'RECORD_ARCHIVE_SHARE_AVAILABLE':'0','RECORD_ARCHIVE_INITIALIZED_ROOT':'',
                                    'RECORD_ARCHIVE_SHARE_SETUP_FAILURE':'cancelled'}):
            backend.startup_registration(app)
        self.assertNotIn('页面',app.text)
        self.assertIn('初始化',app.text)
        self.assertFalse(app.busy)

    def test_install_does_not_import_a_page_reader(self):
        with patch.dict('sys.modules',{'ui_theme':SimpleNamespace(configure=lambda root:None),
                'page_capture':None,'direct_page':None,'visual_page':None,
                'support_diagnostics':SimpleNamespace(attach_callback_reporter=lambda root:None)}):
            backend.install()

    def test_retry_while_busy_reports_why_it_cannot_start(self):
        app=Application();app.busy=True
        ui.receive_share(app)
        self.assertIn('尚未完成',app.text)

    def test_support_report_excludes_archive_paths_chat_text_and_credentials(self):
        work=ROOT/'tests/support-test-work';work.mkdir(exist_ok=True)
        import json
        with tempfile.TemporaryDirectory(dir=work) as folder:
            folder=Path(folder);(folder/'diagnostics').mkdir()
            (folder/'build-info.json').write_text('{"version":"1.0.0.7","hotfix":"test"}',encoding='utf-8')
            (folder/'diagnostics/last-shared-import.json').write_text(json.dumps({
                'messages':4,'original_archive_path':'private-user-path','chat_text':'private-chat',
                'token':'private-credential'}),encoding='utf-8')
            with patch.dict('sys.modules',{'runtime_paths':SimpleNamespace(DATA=folder,RESOURCES=folder)}),patch.object(
                support.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{"wechat_versions":["4.1.15.56"]}')):
                report=support.build_report()
            for secret in ('private-user-path','private-chat','private-credential'):self.assertNotIn(secret,report)
            self.assertIn('4.1.15.56',report)

if __name__=='__main__':unittest.main()
