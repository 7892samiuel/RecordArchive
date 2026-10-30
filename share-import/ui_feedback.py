"""Reviewed UI callbacks for reliable task completion and visible failures."""

def task(self,work,finish,on_error=None):
    import queue
    import threading
    import time
    from support_diagnostics import record,record_error
    if self.busy:
        self.status.set('当前操作尚未完成，请稍候。')
        return
    self.set_busy(True)
    operation=('share_import' if any(name in work.__qualname__ for name in ('receive_share','poll_share')) else
               'export' if 'export' in work.__qualname__ else 'background')
    record('task_started',operation=operation)
    events=queue.Queue();started=time.monotonic()
    def progress(text):events.put(('progress',str(text)))
    def run():
        try:events.put(('done',work(progress)))
        except Exception as error:
            record_error(operation,error)
            events.put(('error',str(error)))
    def fail(message):
        self.status.set(message)
        if on_error:on_error(message)
    def poll():
        for _ in range(100):
            try:kind,value=events.get_nowait()
            except queue.Empty:break
            if kind=='progress':self.status.set(value)
            else:
                self.set_busy(False)
                if kind=='error':fail(value)
                else:
                    try:finish(value);record('task_completed',operation=operation)
                    except Exception as error:
                        record_error('finish_'+operation,error)
                        fail('处理结果未能显示（'+type(error).__name__+'），请复制诊断信息。')
                return
        elapsed=int(time.monotonic()-started)
        if elapsed>=15:self.status.set('仍在处理（'+str(elapsed)+' 秒），完成后会自动显示结果。')
        self.root.after(40,poll)
    try:threading.Thread(target=run,daemon=True).start()
    except Exception as error:
        self.set_busy(False);record_error('start_worker',error);fail(str(error));return
    self.root.after(0,poll)

def receive_share(self):
    from tkinter import messagebox
    from support_diagnostics import record
    record('receive_share_clicked',busy=self.busy)
    if self.busy:
        self.status.set('当前操作尚未完成，请稍候。')
        return
    if self.editor is not None and self.editor.winfo_exists():
        self.editor.lift();self.status.set('请先保存并关闭编辑窗口，再接收新记录。');return
    self.status.set('正在接收微信转发…')
    def work(progress):
        from shared_record_backend import read_pending
        return read_pending()
    def loaded(data):
        if data is not None:self.load_record(data)
        else:self.status.set('暂无待接收记录，请在微信“其他应用”中转发给“记录归档”。')
    def failed(message):messagebox.showerror('未能接收记录',message,parent=self.root)
    self.task(work,loaded,on_error=failed)

def poll_share(self):
    from shared_record_backend import pending_batch_id,read_pending
    from support_diagnostics import record_error
    self.share_timer=None
    try:
        editing=self.editor is not None and self.editor.winfo_exists()
        if not self.busy and not editing:
            pending=pending_batch_id()
            notified=bool(self.share_events and self.share_events.take())
            if pending and (notified or pending!=getattr(self,'_last_automatic_batch',None)):
                self._last_automatic_batch=pending
                self.root.deiconify();self.root.lift()
                self.status.set('正在导入微信分享…')
                def work(progress):return read_pending()
                def loaded(data):
                    if data is not None:self.load_record(data)
                    else:self.status.set('暂无待接收记录，请从微信重新转发。')
                def failed(message):
                    self.status.set('微信分享导入失败：'+message+'；请重新转发或点击“重新接收”。')
                self.task(work,loaded,on_error=failed)
    except Exception as error:
        record_error('share_poll',error)
        self.status.set('微信分享接收暂不可用，请重新打开工具后再从微信转发。')
    finally:self.share_timer=self.root.after(500,self.poll_share)

def show_help(self):
    import tkinter as tk
    from tkinter import ttk
    from display import px
    from font_support import UI_FONT
    from runtime_paths import RESOURCES
    from support_diagnostics import build_report
    dialog=tk.Toplevel(self.root);dialog.title('使用方法');dialog.geometry(str(px(720))+'x'+str(px(540)))
    footer=ttk.Frame(dialog,padding=12);footer.pack(side='bottom',fill='x')
    hint=ttk.Label(footer,text='诊断仅包含版本、注册状态和操作阶段，不含聊天内容。',wraplength=px(600))
    hint.pack(anchor='w',pady=(0,8))
    def copy_report():
        import queue
        import threading
        copy.configure(state='disabled');hint.configure(text='正在收集诊断信息…')
        values=queue.Queue()
        def work():
            try:values.put((True,build_report()))
            except Exception as error:values.put((False,type(error).__name__))
        def poll():
            if not dialog.winfo_exists():return
            try:ok,text=values.get_nowait()
            except queue.Empty:dialog.after(40,poll);return
            copy.configure(state='normal')
            if ok:
                dialog.clipboard_clear();dialog.clipboard_append(text)
                hint.configure(text='诊断信息已复制，可直接粘贴发送。')
            else:hint.configure(text='诊断收集失败：'+text)
        threading.Thread(target=work,daemon=True).start();dialog.after(40,poll)
    copy=ttk.Button(footer,text='复制诊断信息',command=copy_report);copy.pack(anchor='e')
    frame=ttk.Frame(dialog);frame.pack(fill='both',expand=True)
    text=tk.Text(frame,wrap='word',font=(UI_FONT,11),padx=18,pady=16)
    scroll=ttk.Scrollbar(frame,command=text.yview);text.configure(yscrollcommand=scroll.set)
    text.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
    path=RESOURCES/'使用说明.txt'
    text.insert('1.0',path.read_text(encoding='utf-8') if path.is_file() else '微信合并转发 → 其他应用 → 记录归档，收到后自动预览。')
    text.configure(state='disabled')

def register_share():
    from shared_record_backend import startup_registration
    startup_registration(app)
