"""Аудио-движок: микширование в реальном времени, несколько устройств вывода."""
import threading

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal

SR = 48000        # единая частота для всех звуков
CHANNELS = 2
BLOCK = 512       # ~10 мс — низкая задержка


class AudioEngine(QObject):
    """Микшер на callback'е PortAudio. Поддерживает одновременный вывод
    на два устройства (например, виртуальный микрофон + наушники)."""

    playbackStarted = Signal(str)    # id звука
    playbackFinished = Signal(str)
    deviceError = Signal(str)

    class _Stream:
        __slots__ = ('device', 'stream', 'active')

        def __init__(self, device):
            self.device = device
            self.stream = None
            self.active = []          # [sound, позиция]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.master = 1.0
        self._lock = threading.RLock()
        self._devices = []

    # ---------- устройства ----------

    @staticmethod
    def list_devices():
        try:
            return [(i, d['name']) for i, d in enumerate(sd.query_devices())
                    if d.get('max_output_channels', 0) > 0]
        except Exception:
            return []

    def set_devices(self, primary=None, secondary=None):
        want = []
        for d in (primary, secondary):
            if d is not None and d not in want:
                want.append(d)
        if not want:
            want = [None]  # None = устройство по умолчанию

        with self._lock:
            stopped = self._close_all_locked()

        opened = []
        for d in want:
            st = self._Stream(d)
            st.stream = self._open(st)
            if st.stream:
                opened.append(st)

        with self._lock:
            self._devices = opened

        for sid in stopped:
            self.playbackFinished.emit(sid)

        if not opened:
            if want != [None]:
                return self.set_devices()   # откат на устройство по умолчанию
            self.deviceError.emit('Не удалось открыть аудиоустройство')
        else:
            failed = [d for d in want
                      if d is not None and not any(st.device == d for st in opened)]
            if failed:
                self.deviceError.emit(
                    'Не удалось открыть одно из устройств вывода — проверьте настройки')

    def _open(self, st):
        try:
            s = sd.OutputStream(
                device=st.device, samplerate=SR, channels=CHANNELS,
                dtype='float32', blocksize=BLOCK,
                callback=lambda out, frames, t, status, st=st: self._mix(st, out, frames))
            s.start()
            return s
        except Exception:
            return None

    def _close_all_locked(self):
        stopped = []
        for st in self._devices:
            stopped += [it[0].id for it in st.active]
            st.active = []
            try:
                if st.stream:
                    st.stream.close()
            except Exception:
                pass
        self._devices = []
        return stopped

    # ---------- управление ----------

    def play(self, sound):
        if sound.data is None or not len(sound.data):
            return
        with self._lock:
            for st in self._devices:
                st.active = [it for it in st.active if it[0].id != sound.id]
                st.active.append([sound, 0])
        self.playbackStarted.emit(sound.id)

    def stop(self, sound_id):
        with self._lock:
            for st in self._devices:
                st.active = [it for it in st.active if it[0].id != sound_id]
        self.playbackFinished.emit(sound_id)

    def is_playing(self, sound_id):
        with self._lock:
            return any(it[0].id == sound_id
                       for st in self._devices for it in st.active)

    def position(self, sound_id):
        """0..1 — прогресс воспроизведения."""
        with self._lock:
            for st in self._devices:
                for it in st.active:
                    if it[0].id == sound_id and it[0].data is not None:
                        return it[1] / max(1, len(it[0].data))
        return 0.0

    def set_master(self, value):
        self.master = float(min(1.0, max(0.0, value)))

    def close(self):
        with self._lock:
            self._close_all_locked()

    # ---------- микширование (поток PortAudio) ----------

    def _mix(self, st, outdata, frames):
        try:
            with self._lock:
                if not st.active:
                    outdata.fill(0)
                    return
                mix = np.zeros((frames, CHANNELS), dtype=np.float32)
                keep, finished = [], []
                for item in st.active:
                    sound, pos = item
                    chunk = sound.data[pos:pos + frames]
                    n = len(chunk)
                    if n < frames:
                        chunk = np.concatenate(
                            [chunk, np.zeros((frames - n, CHANNELS), np.float32)])
                        finished.append(sound.id)
                    else:
                        item[1] = pos + frames
                        keep.append(item)
                    if n:
                        mix[:n] += chunk[:n] * sound.volume
                st.active = keep
            outdata[:] = np.clip(mix * self.master, -1.0, 1.0)
            for sid in finished:
                self.playbackFinished.emit(sid)
        except Exception:
            try:
                outdata.fill(0)
            except Exception:
                pass