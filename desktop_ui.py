"""Dependency-free desktop workspace; all widgets are owned by the Tk main thread."""
import tkinter as tk
from tkinter import ttk, scrolledtext

BG = '#F3F6F8'
INK = '#182D38'
MUTED = '#627681'
ACCENT = '#087F8C'
LINE = '#DCE5E9'

class WorkspaceUI:
    def _build_ui(self):
        m = self.master
        m.title('MMV Voice · Your words, on your computer')
        m.geometry('1180x780')
        m.minsize(980, 680)
        m.configure(bg=BG)
        m.columnconfigure(0, weight=1)
        m.rowconfigure(1, weight=1)
        m.option_add('*Font', ('DejaVu Sans', 10))
        style = ttk.Style(m)
        style.theme_use('clam')
        style.configure('.', background=BG, foreground=INK, font=('DejaVu Sans', 10))
        style.configure('TFrame', background=BG)
        style.configure('Card.TFrame', background='white')
        style.configure('TButton', padding=(14, 9), borderwidth=1, relief='flat', background='white', bordercolor=LINE)
        style.map('TButton', background=[('active', '#E8EFF2')], foreground=[('disabled', '#96A5AE')])
        style.configure('Accent.TButton', background=ACCENT, foreground='white', bordercolor=ACCENT)
        style.map('Accent.TButton', background=[('disabled', '#CCDBDE'), ('active', '#066773')], foreground=[('disabled', '#627681')])
        style.configure('TCheckbutton', background='white', padding=(0, 7))
        style.configure('TRadiobutton', background='white', padding=(0, 6))
        style.configure('TNotebook', background='white', borderwidth=0)
        style.configure('TNotebook.Tab', padding=(16, 10), background='#EEF3F5', foreground=MUTED)
        style.map('TNotebook.Tab', background=[('selected', 'white')], foreground=[('selected', ACCENT)])
        style.configure('Horizontal.TProgressbar', background=ACCENT, troughcolor='#DFE9EC', borderwidth=0)
        self.file_var = tk.StringVar(value='No recording selected')
        self.file_detail_var = tk.StringVar(value='WAV, MP3, M4A, FLAC and more')
        self.stage_var = tk.StringVar(value='Ready for your recording')
        self.elapsed_var = tk.StringVar(value='')
        self.review_var = tk.StringVar(value='Your original transcript is always preserved.')
        self.privacy_var = tk.StringVar(value='LOCAL PROCESSING')
        header = tk.Frame(m, bg=BG)
        header.grid(row=0, column=0, sticky='ew', padx=26, pady=(22, 16))
        tk.Label(header, text='MMV Voice', bg=BG, fg=INK, font=('DejaVu Sans', 23, 'bold')).pack(side='left')
        tk.Label(header, text='A clear transcript. Your words intact.', bg=BG, fg=MUTED).pack(side='left', padx=22)
        self.privacy_badge = tk.Label(header, textvariable=self.privacy_var, bg='#DFF1ED', fg='#176855', padx=12, pady=7, font=('DejaVu Sans', 9, 'bold'))
        self.privacy_badge.pack(side='right')
        body = tk.Frame(m, bg=BG)
        body.grid(row=1, column=0, sticky='nsew', padx=26)
        side = tk.Frame(body, bg='white', width=244, highlightbackground=LINE, highlightthickness=1)
        side.pack(side='left', fill='y', padx=(0, 18))
        side.pack_propagate(False)
        side_actions = tk.Frame(side, bg='white')
        side_actions.pack(side='bottom', fill='x', padx=18, pady=(8, 14))
        inner = tk.Frame(side, bg='white'); inner.pack(fill='both', expand=True, padx=18, pady=14)
        def label(text, bold=False, pady=(0, 8)):
            tk.Label(inner, text=text, bg='white', fg=INK if bold else MUTED, anchor='w', justify='left', wraplength=200,
                     font=('DejaVu Sans', 10, 'bold' if bold else 'normal')).pack(fill='x', pady=pady)
        # Order and padding matter: at large Tk scaling (HiDPI, e.g. 1.33x–1.8x) the
        # sidebar is height-limited and clips from the bottom, so the essential
        # controls (open, local/cloud choice) come first and the hints come last.
        label('YOUR RECORDING', True, pady=(0, 4))
        tk.Label(inner, textvariable=self.file_var, bg='white', fg=INK, anchor='w', justify='left', wraplength=200).pack(fill='x', pady=(2, 2))
        tk.Label(inner, textvariable=self.file_detail_var, bg='white', fg=MUTED, anchor='w', justify='left', wraplength=200, font=('DejaVu Sans', 9)).pack(fill='x', pady=(0, 8))
        self.select_btn = ttk.Button(inner, text='Open audio…', style='Accent.TButton', command=self.select_file)
        self.select_btn.pack(fill='x')
        ttk.Separator(inner).pack(fill='x', pady=(10, 8))
        label('PROCESSING', True, pady=(0, 2))
        self.engine_m_btn = ttk.Radiobutton(inner, text='On this computer', variable=self.engine_var, value='M', command=self._refresh_privacy)
        self.engine_m_btn.pack(anchor='w')
        self.engine_l_btn = ttk.Radiobutton(inner, text='Groq cloud · optional', variable=self.engine_var, value='L', command=self._confirm_cloud_engine)
        self.engine_l_btn.pack(anchor='w')
        if not self._cloud_available: self.engine_l_btn.state(['disabled'])
        label('Cloud mode sends transcript text. Local is the default.', pady=(4, 6))
        label('Ctrl+O · Open recording  ·  Ctrl+S · Save text', pady=(4, 0))
        self.options_btn = ttk.Button(side_actions, text='Optional steps…', command=self._show_options)
        self.options_btn.pack(fill='x')
        self.option_widgets = [self.options_btn]
        ttk.Button(side_actions, text='Check connection', command=self.recheck_connection).pack(fill='x', pady=(8, 0))
        workspace = tk.Frame(body, bg=BG); workspace.pack(side='left', fill='both', expand=True)
        progress = tk.Frame(workspace, bg='white', highlightbackground=LINE, highlightthickness=1)
        progress.pack(fill='x', pady=(0, 16))
        heading = tk.Frame(progress, bg='white'); heading.pack(fill='x', padx=18, pady=(14, 8))
        tk.Label(heading, textvariable=self.stage_var, bg='white', fg=INK, font=('DejaVu Sans', 11, 'bold')).pack(side='left')
        tk.Label(heading, textvariable=self.elapsed_var, bg='white', fg=MUTED).pack(side='right')
        steps = tk.Frame(progress, bg='white'); steps.pack(fill='x', padx=18, pady=(0, 10))
        self.step_labels = []
        for text in ['01  Transcribe', '02  Punctuate', '03  Review & save']:
            w = tk.Label(steps, text=text, bg='white', fg=MUTED, anchor='w'); w.pack(side='left', expand=True, fill='x'); self.step_labels.append(w)
        self.progressbar = ttk.Progressbar(progress, mode='determinate', length=180)
        self.progressbar.pack(fill='x', padx=18, pady=(0, 12))
        self.kill_btn = ttk.Button(progress, text='Stop after current segment', command=self.kill_whisper, state='disabled')
        self.kill_btn.pack(anchor='e', padx=18, pady=(0, 12))
        footer = tk.Frame(workspace, bg=BG); footer.pack(side='bottom', fill='x', pady=(12, 4))
        tk.Label(footer, textvariable=self.review_var, bg=BG, fg=MUTED, anchor='w', wraplength=420, justify='left').pack(side='left', fill='x', expand=True)
        self.copy_btn = ttk.Button(footer, text='Copy', command=self.copy_active_tab, state='disabled'); self.copy_btn.pack(side='right', padx=(8, 0))
        self.export_btn = ttk.Button(footer, text='Save text…', style='Accent.TButton', command=self.export_text, state='disabled'); self.export_btn.pack(side='right')
        pane = ttk.Panedwindow(workspace, orient='horizontal'); pane.pack(fill='both', expand=True)
        lf = tk.Frame(pane, bg='white', highlightbackground=LINE, highlightthickness=1)
        rf = tk.Frame(pane, bg='white', highlightbackground=LINE, highlightthickness=1)
        pane.add(lf, weight=1); pane.add(rf, weight=1)
        source_head = tk.Frame(lf, bg='white'); source_head.pack(fill='x', padx=14, pady=(12, 6))
        tk.Label(source_head, text='Original', bg='white', fg=INK, font=('DejaVu Sans', 11, 'bold')).pack(side='left')
        ttk.Button(source_head, text='Copy', command=lambda: self.copy_to_clipboard(self.whisper_textbox)).pack(side='right')
        self.whisper_textbox = self._text(lf)
        self._replace_text(self.whisper_textbox, 'Your transcript will appear here.\n\nOpen an audio file to get started.')
        self.whisper_progress = tk.Label(lf, text='Unedited Whisper transcript', bg='white', fg=MUTED, anchor='w', wraplength=330, padx=14, pady=10)
        self.whisper_progress.pack(fill='x')
        self.notebook = ttk.Notebook(rf); self.notebook.pack(fill='both', expand=True, padx=1, pady=1)
        self.fmt_textbox = self._make_tab('Transcript')
        self.fidelity_textbox = self._make_tab('Review')
        self.minutes_textbox = self._make_tab('Notes')
        self._replace_text(self.fmt_textbox, 'A little punctuation.\nThe same words.\n\nYour result will appear here after transcription.')
        self._replace_text(self.fidelity_textbox, 'Compare the source and model candidate here.\n\nIf words or numbers change, the original text is retained.')
        self._replace_text(self.minutes_textbox, 'Choose “Generate meeting notes” before opening a recording to include notes.')
        self.fmt_progress = tk.Label(rf, text='Waiting for a recording', bg='white', fg=MUTED, wraplength=330, anchor='w', padx=14, pady=10)
        self.fmt_progress.pack(fill='x')
        self.digest_btn = ttk.Button(side_actions, text='Save audit digest…', command=self.save_digest, state='disabled')
        self.digest_btn.pack(fill='x', pady=(8, 0))
        bottom = tk.Frame(m, bg=BG); bottom.grid(row=2, column=0, sticky='ew', padx=26, pady=(12, 16))
        tk.Label(bottom, textvariable=self.status_var, bg=BG, fg=MUTED, anchor='w', wraplength=760, justify='left').pack(side='left')
        tk.Label(bottom, textvariable=self.mode_var, bg=BG, fg=MUTED, anchor='e', font=('DejaVu Sans', 8), wraplength=280).pack(side='right')
        for tb in (self.whisper_textbox, self.fmt_textbox, self.fidelity_textbox, self.minutes_textbox): self._add_context_menu(tb)
        m.bind('<Control-o>', lambda e: self.select_file())
        m.bind('<Control-s>', lambda e: self.export_text())

    def _text(self, parent):
        tb = scrolledtext.ScrolledText(parent, font=('DejaVu Sans', 11), width=20, height=10, wrap='word',
            bg='white', fg=INK, relief='flat', borderwidth=0, padx=14, pady=16,
            insertbackground=ACCENT, selectbackground='#CBE9E7', spacing1=3, spacing3=7, state='disabled')
        tb.pack(fill='both', expand=True)
        return tb

    def _make_tab(self, title):
        frame = tk.Frame(self.notebook, bg='white'); self.notebook.add(frame, text=title)
        return self._text(frame)

    @staticmethod
    def _replace_text(tb, text):
        tb.configure(state='normal'); tb.delete('1.0', tk.END); tb.insert(tk.END, text); tb.configure(state='disabled')

    def _show_options(self):
        if self._busy:
            return
        dialog = tk.Toplevel(self.master)
        dialog.title('Optional steps')
        dialog.configure(bg='white')
        dialog.transient(self.master)
        dialog.resizable(False, False)
        frame = tk.Frame(dialog, bg='white', padx=24, pady=24)
        frame.pack()
        tk.Label(frame, text='Make room for what you need.', bg='white', fg=INK,
                 font=('DejaVu Sans', 14, 'bold')).pack(anchor='w', pady=(0, 14))
        for title, var in [('Attribute speakers', self.opt_speaker), ('Extra fidelity check', self.opt_fidelity), ('Generate meeting notes', self.opt_minutes)]:
            ttk.Checkbutton(frame, text=title, variable=var).pack(anchor='w')
        tk.Label(frame, text='Extra steps take more time. Speaker attribution may download a model.\nThe preservation check is always on for local formatting.',
                 bg='white', fg=MUTED, justify='left', wraplength=390).pack(anchor='w', pady=16)
        ttk.Button(frame, text='Done', style='Accent.TButton', command=dialog.destroy).pack(anchor='e')
        dialog.grab_set()
