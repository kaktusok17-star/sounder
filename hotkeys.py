"""Глобальные горячие клавиши (работают при свёрнутом окне)."""
from PySide6.QtCore import QObject, Signal

try:
    import keyboard
except Exception:          # macOS без root / отсутствие модуля
    keyboard = None


class HotkeyManager(QObject):
    triggered = Signal(str)   # id звука

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hooks = {}
        self._bindings = {}   # id -> комбинация (для suspend/resume)

    def bind(self, sound_id, combo):
        """combo = 'ctrl+f1'; None/'' — снять. Возвращает успех."""
        self.unbind(sound_id)
        if not combo:
            self._bindings.pop(sound_id, None)
            return True
        self._bindings[sound_id] = combo
        if keyboard is None:
            return False
        try:
            self._hooks[sound_id] = keyboard.add_hotkey(
                combo, lambda sid=sound_id: self.triggered.emit(sid))
            return True
        except Exception:
            return False

    def unbind(self, sound_id):
        h = self._hooks.pop(sound_id, None)
        if h is not None and keyboard is not None:
            try:
                keyboard.remove_hotkey(h)
            except Exception:
                pass

    def suspend(self):
        for sid in list(self._hooks):
            self.unbind(sid)

    def resume(self):
        for sid, combo in list(self._bindings.items()):
            self.bind(sid, combo)

    def shutdown(self):
        if keyboard is not None:
            try:
                keyboard.unhook_all()
            except Exception:
                pass
        self._hooks.clear()
        self._bindings.clear()