import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.storage.jsonstore import JsonStore
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton

import scanner_core as core

Window.softinput_mode = "below_target"


class ScannerApp(App):
    title = "Binance Scanner"

    def build(self):
        self.running = False
        self.store = JsonStore(self.user_data_dir + "/settings.json")

        root = BoxLayout(orientation="vertical", padding=10, spacing=8)

        self.token = TextInput(hint_text="Telegram bot token (optional)", multiline=False,
                               size_hint_y=None, height=100, text=self._load("token"))
        self.chat = TextInput(hint_text="Telegram chat id (optional)", multiline=False,
                              size_hint_y=None, height=100, text=self._load("chat"))
        self.scan_btn = Button(text="SCAN NOW", size_hint_y=None, height=130,
                               on_release=lambda *_: self.start_scan())
        self.auto = ToggleButton(text="Auto-scan every 60 min (keep app open)",
                                 size_hint_y=None, height=100)
        self.status = Label(text="Ready", size_hint_y=None, height=60)

        self.out = Label(text="Press SCAN NOW", size_hint_y=None,
                         halign="left", valign="top")
        self.out.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        self.out.bind(texture_size=lambda w, ts: setattr(w, "height", ts[1]))
        sv = ScrollView()
        sv.add_widget(self.out)

        for w in (self.token, self.chat, self.scan_btn, self.auto, self.status, sv):
            root.add_widget(w)

        Clock.schedule_interval(self._auto_tick, 3600)
        return root

    def _load(self, key):
        return self.store.get("cfg")[key] if self.store.exists("cfg") and key in self.store.get("cfg") else ""

    def _save(self):
        self.store.put("cfg", token=self.token.text.strip(), chat=self.chat.text.strip())

    def _auto_tick(self, dt):
        if self.auto.state == "down":
            self.start_scan()

    def start_scan(self):
        if self.running:
            return
        self.running = True
        self.scan_btn.disabled = True
        self._save()
        threading.Thread(target=self._work, daemon=True).start()

    def _set_status(self, msg):
        Clock.schedule_once(lambda dt: setattr(self.status, "text", msg))

    def _work(self):
        try:
            results = core.scan(progress=self._set_status)
            text = core.format_results(results)
            tg = core.send_telegram(self.token.text.strip(), self.chat.text.strip(), results)
            self._set_status(f"Done - {len(results)} coins passed filters. {tg}")
        except Exception as e:
            text = f"Error: {e}\n\nIf you see HTTP 451, Binance API is blocked in your region - try a VPN."
            self._set_status("Failed")
        Clock.schedule_once(lambda dt: self._finish(text))

    def _finish(self, text):
        self.out.text = text
        self.running = False
        self.scan_btn.disabled = False


if __name__ == "__main__":
    ScannerApp().run()
