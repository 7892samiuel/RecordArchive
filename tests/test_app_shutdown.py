import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock,patch

source=Path(__file__).parents[1]/'share-import/app_shutdown.py'
spec=importlib.util.spec_from_file_location('app_shutdown_test',source)
shutdown=importlib.util.module_from_spec(spec);spec.loader.exec_module(shutdown)
work=Path(__file__).parent/'shutdown-test-work';work.mkdir(exist_ok=True)

class ShutdownTests(unittest.TestCase):
    def application(self):
        return SimpleNamespace(busy=False,editor=None,root=SimpleNamespace(destroy=Mock(),after_cancel=Mock()),
                               preview=SimpleNamespace(clear=Mock()),share_timer='job',share_events=SimpleNamespace(close=Mock()))

    def test_cleanup_and_preview_failures_do_not_trap_window(self):
        with tempfile.TemporaryDirectory(dir=work) as root:
            app=self.application();app.preview.clear.side_effect=RuntimeError('preview already destroyed')
            app.root.after_cancel.side_effect=RuntimeError('timer already expired')
            runtime=SimpleNamespace(DATA=Path(root),cleanup_temporary=Mock(side_effect=PermissionError('temporary file locked')))
            with patch.dict('sys.modules',{'runtime_paths':runtime,'tkinter':SimpleNamespace(messagebox=Mock())}):shutdown.close(app)
            app.root.destroy.assert_called_once();app.share_events.close.assert_called_once()
            self.assertTrue((Path(root)/'diagnostics/last-shutdown.json').is_file())

    def test_active_operation_is_not_killed(self):
        app=self.application();app.busy=True;messagebox=Mock()
        with patch.dict('sys.modules',{'runtime_paths':SimpleNamespace(DATA=work,cleanup_temporary=Mock()),'tkinter':SimpleNamespace(messagebox=messagebox)}):shutdown.close(app)
        app.root.destroy.assert_not_called();messagebox.showinfo.assert_called_once()

    def test_unsaved_edit_is_preserved_when_exit_is_declined(self):
        app=self.application();app.editor=SimpleNamespace(winfo_exists=Mock(return_value=True),lift=Mock(),destroy=Mock())
        messagebox=Mock();messagebox.askyesno.return_value=False
        with patch.dict('sys.modules',{'runtime_paths':SimpleNamespace(DATA=work,cleanup_temporary=Mock()),'tkinter':SimpleNamespace(messagebox=messagebox)}):shutdown.close(app)
        app.editor.lift.assert_called_once();app.editor.destroy.assert_not_called();app.root.destroy.assert_not_called()

if __name__=='__main__':unittest.main()
