"""
gui.py
"Sapce" -- a Gemini-style chat UI (sidebar + rounded message bubbles + pill
input bar) in a purple theme, built with CustomTkinter. Connects to any
database, auto-scans its schema, answers questions about your data, and
manages alerts.
Run: python gui.py
"""
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
import threading
import queue
import time
from sqlalchemy import text as sql_text

import db_connection
import schema_scanner
from rag_engine import answer_question
from alerts import init_app_db, add_alert, list_alerts, remove_alert, check_alerts

ALERT_CHECK_INTERVAL_SECONDS = 60
event_queue = queue.Queue()

# ---- Purple theme -----------------------------------------------------
BG_MAIN = "#000208"
BG_SIDEBAR = "#2D0321"
BG_HEADER = "#000000"
BG_CARD = "#230221"
ACCENT = "#332F38"
ACCENT_HOVER = "#359c84"
BUBBLE_USER = "#BE279B"
BUBBLE_ASSISTANT = "#292932"
TEXT_PRIMARY = "#f3f0ff"
TEXT_SECONDARY = "#fdfdfd"
TEXT_MUTED = "#fcfbff"
BORDER = "#ffffff"

ctk.set_appearance_mode("dark")


class ScrollableArea(ctk.CTkFrame):
    """A scrollable container built entirely on plain Tkinter APIs
    (Canvas, bindtags, bind_class) rather than any private internals of
    CustomTkinter. This guarantees mouse-wheel/trackpad scrolling works
    the same way no matter which CustomTkinter version is installed --
    previous attempts relied on private attributes that can differ or
    change between versions.
    Add content via scroll_area.inner as the parent widget, then call
    scroll_area.enable_scroll(widget) on whatever you add so wheel events
    over it (and all its children) are routed to this area's canvas.
    """
    _counter = 0

    def __init__(self, master, fg_color=BG_MAIN, corner_radius=0):
        super().__init__(master, fg_color=fg_color, corner_radius=corner_radius)
        ScrollableArea._counter += 1
        self._tag = f"sapce_scroll_{ScrollableArea._counter}"

        self.canvas = tk.Canvas(self, bg=fg_color, highlightthickness=0)
        self.scrollbar = ctk.CTkScrollbar(self, orientation="vertical", command=self.canvas.yview)
        self.inner = ctk.CTkFrame(self.canvas, fg_color=fg_color, corner_radius=0)

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self._window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self._window_id, width=e.width))

        # bind_class + bindtags are standard, stable Tkinter APIs (unlike
        # CustomTkinter's private attributes), so this works regardless of
        # which CTk version is installed on the user's machine. Each
        # ScrollableArea gets its own tag so multiple scroll areas in the
        # same app (e.g. chat + alerts list) never interfere with each other.
        self.bind_class(self._tag, "<MouseWheel>", self._on_wheel, add="+")
        self.bind_class(self._tag, "<Button-4>", self._on_wheel, add="+")
        self.bind_class(self._tag, "<Button-5>", self._on_wheel, add="+")

    def _on_wheel(self, event):
        delta = getattr(event, "delta", 0)
        if delta:
            step = -1 if delta > 0 else 1
        else:
            step = -1 if getattr(event, "num", 5) == 4 else 1
        if self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(step, "units")

    def enable_scroll(self, widget):
        """Tags this widget and all its current children so wheel events
        anywhere over them scroll this area. Call after adding content."""
        tags = widget.bindtags()
        if self._tag not in tags:
            widget.bindtags((self._tag,) + tags)
        for child in widget.winfo_children():
            self.enable_scroll(child)

    def clear(self):
        for child in self.inner.winfo_children():
            child.destroy()

    def scroll_to_bottom(self):
        self.canvas.yview_moveto(1.0)


class ConnectDialog(ctk.CTkToplevel):
    def __init__(self, master, on_connected, is_initial=False):
        super().__init__(master, fg_color=BG_MAIN)
        self.title("Connect to your database")
        self.geometry("440x300")
        self.resizable(False, False)
        self.on_connected = on_connected
        self.is_initial = is_initial
        self.grab_set()
        # If this is the very first connect dialog (shown before the main
        # window is ever visible) and the user closes it without
        # connecting, there'd be nothing left on screen but the app would
        # keep running invisibly forever. Closing it should quit the app
        # instead. If it's a later "Change Database" dialog, closing it
        # should just cancel and leave the existing session running.
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        ctk.CTkLabel(self, text="Connect to your database", text_color=TEXT_PRIMARY,
                     font=("", 15, "bold")).pack(anchor="w", padx=20, pady=(20, 4))
        ctk.CTkLabel(
            self,
            text="Examples: business.db  |  sqlite:///path/to/file.db\n"
                 "postgresql://user:pass@host:5432/dbname\n"
                 "mysql+pymysql://user:pass@host/dbname",
            text_color=TEXT_MUTED, justify="left", font=("", 11), anchor="w",
        ).pack(anchor="w", padx=20)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=14)
        self.conn_entry = ctk.CTkEntry(row, fg_color=BG_CARD, text_color=TEXT_PRIMARY,
                                        border_width=0, corner_radius=10)
        self.conn_entry.insert(0, "business.db")
        self.conn_entry.pack(side="left", fill="x", expand=True, ipady=4)
        ctk.CTkButton(row, text="Browse", width=80, corner_radius=10,
                      fg_color=BG_CARD, hover_color=BORDER, text_color=TEXT_PRIMARY,
                      command=self.browse_file).pack(side="left", padx=(8, 0))

        self.status_label = ctk.CTkLabel(self, text="", text_color="#f87171",
                                          wraplength=380, justify="left", font=("", 11))
        self.status_label.pack(anchor="w", padx=20)

        ctk.CTkButton(self, text="Connect", corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self.try_connect).pack(pady=20)

    def _on_close(self):
        if self.is_initial:
            self.master.destroy()
        else:
            self.destroy()

    def browse_file(self):
        path = filedialog.askopenfilename(title="Choose a SQLite database file")
        if path:
            self.conn_entry.delete(0, "end")
            self.conn_entry.insert(0, path)

    def try_connect(self):
        conn_str = self.conn_entry.get().strip()
        if not conn_str:
            self.status_label.configure(text="Enter a connection string.", text_color="#f87171")
            return
        self.status_label.configure(text="Connecting and scanning schema...", text_color=ACCENT)
        self.update()
        try:
            engine = db_connection.connect(conn_str)
            schema_text, tables = schema_scanner.scan_schema(engine)
            if not tables:
                self.status_label.configure(text="Connected, but no tables were found.", text_color="#fbbf24")
                return
        except Exception as e:
            self.status_label.configure(text=f"Failed to connect: {e}", text_color="#f87171")
            return
        self.destroy()
        self.on_connected(tables)


class AlertDialog(ctk.CTkToplevel):
    def __init__(self, master, tables, on_saved=None):
        super().__init__(master, fg_color=BG_MAIN)
        self.title("Set Alert")
        self.geometry("420x600")
        self.minsize(400, 560)
        self.resizable(False, True)
        self.tables = tables
        self.on_saved = on_saved
        self.grab_set()

        def field(label_text):
            ctk.CTkLabel(self, text=label_text, text_color=TEXT_SECONDARY,
                         font=("", 11), anchor="w").pack(fill="x", padx=20, pady=(10, 2))

        field("Description")
        self.desc_entry = ctk.CTkEntry(self, fg_color=BG_CARD, text_color=TEXT_PRIMARY,
                                        border_width=0, corner_radius=8)
        self.desc_entry.pack(fill="x", padx=20)

        field("Table")
        self.table_box = ctk.CTkComboBox(self, values=list(tables.keys()), fg_color=BG_CARD,
                                          button_color=ACCENT, button_hover_color=ACCENT_HOVER,
                                          text_color=TEXT_PRIMARY, dropdown_fg_color=BG_CARD,
                                          command=self.on_table_selected)
        self.table_box.set("")
        self.table_box.pack(fill="x", padx=20)

        field("Column (numeric)")
        self.column_box = ctk.CTkComboBox(self, values=[""], fg_color=BG_CARD,
                                           button_color=ACCENT, button_hover_color=ACCENT_HOVER,
                                           text_color=TEXT_PRIMARY, dropdown_fg_color=BG_CARD)
        self.column_box.pack(fill="x", padx=20)

        field("Identifier column (optional)")
        self.id_box = ctk.CTkComboBox(self, values=[""], fg_color=BG_CARD,
                                       button_color=ACCENT, button_hover_color=ACCENT_HOVER,
                                       text_color=TEXT_PRIMARY, dropdown_fg_color=BG_CARD,
                                       command=self.on_identifier_selected)
        self.id_box.pack(fill="x", padx=20)

        field("Apply to")
        self.value_box = ctk.CTkComboBox(self, values=["(All rows)"], fg_color=BG_CARD,
                                          button_color=ACCENT, button_hover_color=ACCENT_HOVER,
                                          text_color=TEXT_PRIMARY, dropdown_fg_color=BG_CARD)
        self.value_box.set("(All rows)")
        self.value_box.pack(fill="x", padx=20)

        field("Condition")
        self.cond_box = ctk.CTkComboBox(self, values=["below", "above", "equal"], fg_color=BG_CARD,
                                         button_color=ACCENT, button_hover_color=ACCENT_HOVER,
                                         text_color=TEXT_PRIMARY, dropdown_fg_color=BG_CARD)
        self.cond_box.set("below")
        self.cond_box.pack(fill="x", padx=20)

        field("Threshold")
        self.threshold_entry = ctk.CTkEntry(self, fg_color=BG_CARD, text_color=TEXT_PRIMARY,
                                             border_width=0, corner_radius=8)
        self.threshold_entry.pack(fill="x", padx=20)

        ctk.CTkButton(self, text="Save Alert", corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self.save).pack(pady=18)

    def on_table_selected(self, table):
        columns = self.tables.get(table, {}).get("columns", [])
        self.column_box.configure(values=columns)
        if columns:
            self.column_box.set(columns[0])
        self.id_box.configure(values=[""] + columns)
        self.id_box.set("")
        self.value_box.configure(values=["(All rows)"])
        self.value_box.set("(All rows)")

    def on_identifier_selected(self, id_col):
        if not id_col:
            self.value_box.configure(values=["(All rows)"])
            self.value_box.set("(All rows)")
            return
        table = self.table_box.get().strip()
        values = ["(All rows)"]
        try:
            engine = db_connection.get_engine()
            with engine.connect() as conn:
                result = conn.execute(sql_text(f"SELECT DISTINCT {id_col} FROM {table} LIMIT 200"))
                values += [str(row[0]) for row in result.fetchall() if row[0] is not None]
        except Exception:
            pass  # fall back to just "(All rows)" if the lookup fails
        self.value_box.configure(values=values)
        self.value_box.set("(All rows)")

    def save(self):
        desc = self.desc_entry.get().strip()
        table = self.table_box.get().strip()
        column = self.column_box.get().strip()
        id_col = self.id_box.get().strip() or None
        id_value = self.value_box.get().strip()
        if not id_col or id_value == "(All rows)":
            id_value = None
        condition = self.cond_box.get().strip()
        try:
            threshold = float(self.threshold_entry.get().strip())
        except ValueError:
            messagebox.showerror("Invalid", "Threshold must be a number.")
            return
        if not (desc and table and column):
            messagebox.showerror("Invalid", "Description, table, and column are required.")
            return
        add_alert(desc, table, column, condition, threshold, id_col, id_value)
        messagebox.showinfo("Saved", "Alert saved.")
        if self.on_saved:
            self.on_saved()
        self.destroy()


class AlertsListWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master, fg_color=BG_MAIN)
        self.title("Alerts")
        self.geometry("560x420")
        self.resizable(False, False)
        self._alert_ids = []
        self._rows_frame = None
        self._app = master  # SapceApp instance, gives us access to .tables

        header_row = ctk.CTkFrame(self, fg_color="transparent")
        header_row.pack(fill="x", padx=20, pady=(18, 8))
        ctk.CTkLabel(header_row, text="Your alerts", text_color=TEXT_PRIMARY,
                     font=("", 14, "bold")).pack(side="left")
        ctk.CTkButton(header_row, text="＋ Set Alert", corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, width=110,
                      command=self.open_add_alert).pack(side="right")

        self.scroll = ScrollableArea(self, fg_color=BG_CARD, corner_radius=10)
        self.scroll.pack(fill="both", expand=True, padx=20)

        ctk.CTkButton(self, text="Remove Selected", corner_radius=10, fg_color=BG_CARD,
                      hover_color=BORDER, text_color=TEXT_PRIMARY,
                      command=self.remove_selected).pack(pady=14)

        self._selected_id = None
        self.refresh()

    def open_add_alert(self):
        if not self._app.tables:
            messagebox.showwarning("Not connected", "Connect to a database first.")
            return
        AlertDialog(self, self._app.tables, on_saved=self.refresh)

    def refresh(self):
        self.scroll.clear()
        self._alert_ids = []
        self._selected_id = None
        rows = list_alerts()
        if not rows:
            ctk.CTkLabel(self.scroll.inner, text="No alerts set yet.", text_color=TEXT_MUTED).pack(
                anchor="w", padx=8, pady=8)
            return
        for r in rows:
            alert_id, desc, table, column, id_col, id_value, condition, threshold, active = r
            self._alert_ids.append(alert_id)
            scope = f"{id_col}={id_value}" if id_value else "all rows"
            text = (f"#{alert_id} | {desc} | {table}.{column} ({scope}) "
                    f"{condition} {threshold} | active={bool(active)}")
            item = ctk.CTkButton(
                self.scroll.inner, text=text, anchor="w", corner_radius=6,
                fg_color=BG_CARD, hover_color=BORDER, text_color=TEXT_SECONDARY,
                command=lambda aid=alert_id, i=len(self._alert_ids) - 1: self._select(aid, i),
            )
            item.pack(fill="x", pady=2)
        self.scroll.enable_scroll(self.scroll.inner)

    def _select(self, alert_id, index):
        self._selected_id = alert_id
        for i, child in enumerate(self.scroll.inner.winfo_children()):
            child.configure(fg_color=(ACCENT if i == index else BG_CARD))

    def remove_selected(self):
        if self._selected_id is None:
            messagebox.showinfo("Nothing selected", "Select an alert to remove first.")
            return
        if remove_alert(self._selected_id):
            self.refresh()
        else:
            messagebox.showerror("Error", "Could not remove that alert.")


class ChatBubble(ctk.CTkFrame):
    def __init__(self, master, who, text, thinking=False):
        super().__init__(master, fg_color="transparent")
        is_user = (who == "You")
        bubble_color = BUBBLE_USER if is_user else BUBBLE_ASSISTANT
        text_color = "#ffffff" if is_user else (TEXT_MUTED if thinking else TEXT_PRIMARY)
        self._full_text = text

        if not is_user:
            avatar = ctk.CTkLabel(self, text="S", width=28, height=28, corner_radius=14,
                                   fg_color=ACCENT, text_color="white", font=("", 11, "bold"))
            avatar.pack(side="left", padx=(0, 8), anchor="n")

        bubble_column = ctk.CTkFrame(self, fg_color="transparent")
        bubble_column.pack(side="right" if is_user else "left")

        bubble = ctk.CTkFrame(bubble_column, fg_color=bubble_color, corner_radius=16)
        bubble.pack(anchor="e" if is_user else "w")
        font = ("", 12, "italic") if thinking else ("", 12)
        ctk.CTkLabel(bubble, text=text, text_color=text_color, wraplength=380,
                     justify="left", font=font, anchor="w").pack(padx=16, pady=10)

        if not thinking:
            copy_btn = ctk.CTkButton(
                bubble_column, text="Copy", width=44, height=18, corner_radius=6,
                fg_color="transparent", hover_color=BORDER, text_color=TEXT_MUTED,
                font=("", 9), command=self._copy_text,
            )
            copy_btn.pack(anchor="e" if is_user else "w", pady=(2, 0))

    def _copy_text(self):
        self.clipboard_clear()
        self.clipboard_append(self._full_text)


class SapceApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Sapce")
        self.geometry("920x640")
        self.configure(fg_color=BG_MAIN)
        self.tables = {}
        self._thinking_bubble = None

        self._build_sidebar()
        self._build_main_area()

        init_app_db()
        self.withdraw()
        self.open_connect_dialog(is_initial=True)

        threading.Thread(target=self._alert_watcher, daemon=True).start()
        self.after(200, self._poll_queue)

    # ---- layout ---------------------------------------------------
    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=220, fg_color=BG_SIDEBAR, corner_radius=0)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        ctk.CTkLabel(sidebar, text="✨ Sapce", text_color=TEXT_PRIMARY,
                     font=("", 18, "bold")).pack(anchor="w", padx=18, pady=(22, 26))

        def nav_button(text, command):
            btn = ctk.CTkButton(
                sidebar, text=text, command=command, anchor="w", corner_radius=8,
                fg_color="transparent", hover_color=BG_CARD, text_color=TEXT_SECONDARY,
                font=("", 12),
            )
            btn.pack(fill="x", padx=10, pady=3)
            return btn

        nav_button("＋  New Chat", self.new_chat)
        nav_button("🗄  Connect Database", self.open_connect_dialog)
        nav_button("🔔  Set Alert", self.open_alert_dialog)
        nav_button("📋  View Alerts", self.open_alerts_list)

        self.sidebar_status = ctk.CTkLabel(
            sidebar, text="Not connected", text_color=TEXT_MUTED,
            font=("", 10), wraplength=190, justify="left", anchor="w",
        )
        self.sidebar_status.pack(side="bottom", anchor="w", padx=18, pady=18)

    def _build_main_area(self):
        main = ctk.CTkFrame(self, fg_color=BG_MAIN, corner_radius=0)
        main.pack(side="left", fill="both", expand=True)

        header = ctk.CTkFrame(main, height=52, fg_color=BG_HEADER, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="Sapce", text_color=TEXT_PRIMARY,
                     font=("", 14, "bold")).pack(side="left", padx=20)
        ctk.CTkLabel(header, text="ask about your firm's data", text_color=TEXT_MUTED,
                     font=("", 10)).pack(side="left")

        self.chat_scroll = ScrollableArea(main, fg_color=BG_MAIN, corner_radius=0)
        self.chat_scroll.pack(fill="both", expand=True, padx=8)

        input_bar = ctk.CTkFrame(main, fg_color=BG_MAIN, corner_radius=0)
        input_bar.pack(fill="x", padx=20, pady=16)
        pill = ctk.CTkFrame(input_bar, fg_color=BG_CARD, corner_radius=24)
        pill.pack(fill="x")

        self.entry = ctk.CTkEntry(pill, fg_color="transparent", text_color=TEXT_PRIMARY,
                                   border_width=0, font=("", 12),
                                   placeholder_text="Ask about your data...")
        self.entry.pack(side="left", fill="x", expand=True, padx=(16, 8), pady=10)
        self.entry.bind("<Return>", lambda e: self.send_question())
        self.entry.bind("<KP_Enter>", lambda e: self.send_question())

        ctk.CTkButton(pill, text="➤", width=40, corner_radius=20, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self.send_question).pack(
            side="right", padx=6, pady=6)

        self._welcome_message()

    def _welcome_message(self):
        self.add_bubble("Assistant", "Hi, I'm Sapce. Connect a database and ask me "
                                      "anything about your firm's data")

    def new_chat(self):
        self.chat_scroll.clear()
        self._welcome_message()

    # ---- bubbles ----------------------------------------------------
    def add_bubble(self, who, text, thinking=False):
        bubble = ChatBubble(self.chat_scroll.inner, who, text, thinking=thinking)
        bubble.pack(fill="x", pady=6, padx=8, anchor="e" if who == "You" else "w")
        self.chat_scroll.enable_scroll(bubble)
        self.after(10, self.chat_scroll.scroll_to_bottom)
        return bubble

    # ---- dialogs ------------------------------------------------------
    def open_connect_dialog(self, is_initial=False):
        ConnectDialog(self, on_connected=self._on_connected, is_initial=is_initial)

    def _on_connected(self, tables):
        self.tables = tables
        self.deiconify()
        self.update_idletasks()
        self.entry.focus_set()
        table_list = ", ".join(tables.keys())
        self.sidebar_status.configure(text=f"Connected: {len(tables)} table(s)\n{table_list}")
        self.add_bubble(
            "Assistant",
            f"Connected! Found {len(tables)} table(s): {table_list}.\n"
            f"Ask me anything about your data, e.g. 'what were total sales "
            f"this month' or 'which items are low in stock'.",
        )

    def open_alert_dialog(self):
        if not self.tables:
            messagebox.showwarning("Not connected", "Connect to a database first.")
            return
        AlertDialog(self, self.tables)

    def open_alerts_list(self):
        AlertsListWindow(self)

    # ---- chat ---------------------------------------------------------
    def send_question(self):
        question = self.entry.get().strip()
        if not question:
            return
        if not db_connection.is_connected():
            messagebox.showwarning("Not connected", "Connect to a database first.")
            return
        self.entry.delete(0, "end")
        self.entry.focus_set()
        self.add_bubble("You", question)
        self._thinking_bubble = self.add_bubble("Assistant", "Thinking…", thinking=True)
        threading.Thread(target=self._get_answer, args=(question,), daemon=True).start()

    def _get_answer(self, question):
        try:
            answer = answer_question(question)
        except Exception as e:
            answer = (
                f"Error talking to Ollama: {e}\n"
                "Make sure Ollama is running (`ollama serve`) and the model "
                "in rag_engine.py has been pulled (`ollama pull llama3.1`)."
            )
        event_queue.put(("chat", answer))

    def _alert_watcher(self):
        while True:
            if db_connection.is_connected():
                try:
                    triggered = check_alerts()
                    for msg in triggered:
                        event_queue.put(("alert", msg))
                except Exception as e:
                    event_queue.put(("alert", f"[alert watcher error] {e}"))
            time.sleep(ALERT_CHECK_INTERVAL_SECONDS)

    def _poll_queue(self):
        try:
            while True:
                kind, payload = event_queue.get_nowait()
                if kind == "chat":
                    if self._thinking_bubble is not None:
                        self._thinking_bubble.destroy()
                        self._thinking_bubble = None
                    self.add_bubble("Assistant", payload)
                elif kind == "alert":
                    self.add_bubble("Assistant", f"🔔 {payload}")
        except queue.Empty:
            pass
        self.after(200, self._poll_queue)


def main():
    app = SapceApp()
    app.mainloop()


if __name__ == "__main__":
    main()