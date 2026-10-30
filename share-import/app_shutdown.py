"""The idle window must close even when temporary-file cleanup needs a retry."""

def close(self):
    import json
    from tkinter import messagebox
    from runtime_paths import DATA, cleanup_temporary

    if self.busy:
        messagebox.showinfo('正在处理','请等待当前读取或导出完成后再关闭。',parent=self.root)
        return
    editor=getattr(self,'editor',None)
    if editor is not None and editor.winfo_exists():
        if not messagebox.askyesno('关闭记录归档','编辑窗口尚未关闭。是否放弃未保存的编辑并退出？',parent=editor):
            editor.lift()
            return
        editor.destroy()
        self.editor=None
    failures=[]
    actions=[('preview',lambda:self.preview.clear()),('temporary_files',cleanup_temporary)]
    if getattr(self,'share_timer',None):actions.append(('timer',lambda:self.root.after_cancel(self.share_timer)))
    if getattr(self,'share_events',None):actions.append(('share_events',self.share_events.close))
    for label,action in actions:
        try:action()
        except Exception as error:failures.append(label+':'+type(error).__name__)
    if failures:
        try:
            folder=DATA/'diagnostics';folder.mkdir(parents=True,exist_ok=True)
            (folder/'last-shutdown.json').write_text(json.dumps({'cleanup_retry_required':True,'errors':failures}),encoding='utf-8')
        except OSError:pass
    self.root.destroy()
