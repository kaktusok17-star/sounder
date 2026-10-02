"""Звуки, директории (категории), настройки. Атомарное сохранение в JSON."""
import json
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 48000
CONFIG_DIR = Path.home() / '.sounder'
LIB_FILE = CONFIG_DIR / 'library.json'
SETTINGS_FILE = CONFIG_DIR / 'settings.json'
AUDIO_EXTS = {'.wav', '.mp3', '.flac', '.ogg', '.oga', '.opus'}


class Category:
    """Директория звуков."""
    def __init__(self, name, cid=None):
        self.id = cid or uuid.uuid4().hex[:8]
        self.name = (name or '').strip() or 'Новая директория'


class Sound:
    def __init__(self, path, name=None, volume=1.0, hotkey=None,
                 category=None, sid=None):
        self.id = sid or uuid.uuid4().hex[:10]
        self.path = str(path)
        self.name = name or Path(path).stem
        self.volume = volume
        self.hotkey = hotkey
        self.category = category          # id директории или None
        self.data = None                  # float32 [n, 2], 48 кГц
        self.duration = 0.0

    def load(self):
        data, sr = sf.read(self.path, dtype='float32', always_2d=True)
        if data.size == 0:
            raise ValueError('пустой файл')
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2]
        if sr != SR:                                   # ресемплинг до 48 кГц
            n = max(1, round(len(data) * SR / sr))
            t = np.linspace(0.0, len(data) - 1, n)
            base = np.arange(len(data))
            out = np.empty((n, 2), dtype=np.float32)
            for c in range(2):
                out[:, c] = np.interp(t, base, data[:, c])
            data = out
        self.data = np.ascontiguousarray(data, dtype=np.float32)
        self.duration = len(self.data) / SR


class SoundLibrary:
    def __init__(self):
        self.sounds = []
        self.categories = []
        self._by_id = {}
        self._cat_by_id = {}

    def get(self, sid):
        return self._by_id.get(sid)

    def category(self, cid):
        return self._cat_by_id.get(cid)

    # ---------- директории ----------

    def add_category(self, name):
        cat = Category(name)
        self.categories.append(cat)
        self._cat_by_id[cat.id] = cat
        return cat

    def rename_category(self, cid, name):
        cat = self._cat_by_id.get(cid)
        if cat is not None:
            cat.name = (name or '').strip() or cat.name

    def remove_category(self, cid):
        cat = self._cat_by_id.pop(cid, None)
        if cat is None:
            return
        if cat in self.categories:
            self.categories.remove(cat)
        for s in self.sounds:                # звуки остаются, но без директории
            if s.category == cid:
                s.category = None

    def move_category(self, cid, delta):
        """Сдвигает директорию вверх (delta<0) или вниз (delta>0)."""
        idx = next((i for i, c in enumerate(self.categories) if c.id == cid),
                   None)
        if idx is None:
            return False
        j = idx + (1 if delta > 0 else -1)
        if not (0 <= j < len(self.categories)):
            return False
        self.categories[idx], self.categories[j] = \
            self.categories[j], self.categories[idx]
        return True

    def category_name(self, sound):
        cat = self._cat_by_id.get(sound.category)
        return cat.name if cat else ''

    # ---------- звуки ----------

    def add(self, sound):
        self.sounds.append(sound)
        self._by_id[sound.id] = sound

    def remove(self, sound):
        if sound in self.sounds:
            self.sounds.remove(sound)
        self._by_id.pop(sound.id, None)

    def reorder_sound(self, sound, target_index):
        """Переставляет звук на позицию target_index (индекс в исходном
        списке). Возвращает успех."""
        try:
            self.sounds.remove(sound)
        except ValueError:
            return False
        idx = max(0, min(int(target_index), len(self.sounds)))
        self.sounds.insert(idx, sound)
        return True

    # ---------- сохранение ----------

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            'categories': [{'id': c.id, 'name': c.name}
                           for c in self.categories],
            'sounds': [{'id': s.id, 'path': s.path, 'name': s.name,
                        'volume': round(s.volume, 3), 'hotkey': s.hotkey,
                        'category': s.category} for s in self.sounds],
        }
        tmp = LIB_FILE.with_suffix('.tmp')             # атомарная запись
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding='utf-8')
        tmp.replace(LIB_FILE)

    def load_all(self):
        """Возвращает список файлов, которые не удалось загрузить."""
        self.sounds.clear()
        self._by_id.clear()
        self.categories.clear()
        self._cat_by_id.clear()
        failed = []
        if not LIB_FILE.exists():
            return failed
        try:
            data = json.loads(LIB_FILE.read_text(encoding='utf-8'))
        except Exception:
            return ['<библиотека повреждена>']
        # старый формат (просто список звуков) тоже читаем
        if isinstance(data, list):
            items, cats = data, []
        else:
            items = data.get('sounds', [])
            cats = data.get('categories', [])
        for c in cats:
            cat = Category(c.get('name', ''), c.get('id'))
            self.categories.append(cat)
            self._cat_by_id[cat.id] = cat
        for it in items:
            s = Sound(it.get('path', ''), it.get('name'),
                      it.get('volume', 1.0), it.get('hotkey'),
                      it.get('category'), it.get('id'))
            try:
                s.load()
            except Exception:
                failed.append(s.path)
                continue
            self.add(s)
        return failed


class Settings:
    def __init__(self):
        self.primary = None      # None = по умолчанию, иначе id устройства
        self.secondary = None
        self.master = 1.0
        self.theme = 'auto'      # auto | light | dark

    def load(self):
        if not SETTINGS_FILE.exists():
            return
        try:
            d = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
            self.primary = d.get('primary')
            self.secondary = d.get('secondary')
            self.master = float(d.get('master') or 1.0)
            self.theme = d.get('theme', 'auto')
        except Exception:
            pass

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {'primary': self.primary, 'secondary': self.secondary,
                'master': round(self.master, 3), 'theme': self.theme}
        SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                 encoding='utf-8')