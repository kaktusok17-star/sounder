"""Интерфейс: Fluent-дизайн, welcome-экран, директории, саундбар, настройки."""
import math
import sys
import weakref
from pathlib import Path

import numpy as np

from PySide6.QtCore import (QEasingCurve, QEvent, QMimeData, QPoint, Property,
                            QPropertyAnimation, QRect, QRectF, QPointF, Qt,
                            QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import (QAction, QBrush, QColor, QDrag, QIcon,
                           QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient)
from PySide6.QtWidgets import (QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QMenu, QVBoxLayout, QWidget)

from qfluentwidgets import (BodyLabel, CaptionLabel, CardWidget, ComboBox,
                            FluentIcon, FluentWindow, InfoBar, InfoBarPosition,
                            LineEdit, MessageBox, MessageBoxBase,
                            NavigationItemPosition, PrimaryPushButton, PushButton,
                            ScrollArea, SearchLineEdit, Slider, StrongBodyLabel,
                            SubtitleLabel, Theme, TitleLabel, ToolButton,
                            TransparentToolButton, isDarkTheme, setTheme)

try:                                  # меню в стиле Fluent…
    from qfluentwidgets import Action, RoundMenu
    _FLUENT_MENU = True
except Exception:                     # …или обычное QMenu на старых версиях
    _FLUENT_MENU = False

try:
    import keyboard
except Exception:
    keyboard = None

from engine import AudioEngine
from hotkeys import HotkeyManager
from library import AUDIO_EXTS, Sound, SoundLibrary, Settings

ACCENT = QColor('#0078d4')
MIME_SOUND = 'application/x-sounder-sound'   # mime для перетаскивания звуков
MODS = {'ctrl', 'left ctrl', 'right ctrl', 'alt', 'left alt', 'right alt',
        'shift', 'left shift', 'right shift', 'windows', 'left windows',
        'right windows'}
CAT_COLORS = ['#e3008c', '#8764b8', '#107c10', '#00b7c3', '#ca5010',
              '#f7630c', '#c239b3', '#038387']


def _fmt_duration(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    return f'{m}:{s:02d}' if m else f'{s} с'


def _fmt_time(sec: float) -> str:
    sec = max(0, int(round(sec)))
    return f'{sec // 60}:{sec % 60:02d}'


def _cat_color(name: str) -> QColor:
    return QColor(CAT_COLORS[sum(ord(c) for c in name) % len(CAT_COLORS)])


def ficon(*names, fallback=FluentIcon.EDIT):
    """Безопасный доступ к FluentIcon: пробует несколько имён по очереди
    (не все иконки есть в старых версиях qfluentwidgets). Готовый FluentIcon
    передаём как есть."""
    for n in names:
        if isinstance(n, str):
            try:
                return getattr(FluentIcon, n)
            except AttributeError:
                continue
        else:
            return n
    return fallback


# ===================== меню, совместимые с версиями qfluentwidgets =====================

def make_menu(parent=None):
    return RoundMenu(parent=parent) if _FLUENT_MENU else QMenu(parent)


def _plain_action(icon, text, parent):
    act = QAction(text, parent)
    try:
        act.setIcon(icon.icon() if hasattr(icon, 'icon') else QIcon())
    except Exception:
        pass
    return act


def menu_action(icon, text, handler, parent=None):
    """Пункт меню: работает и с qfluentwidgets, и с обычным QMenu.
    Сигнал подключаем через .connect — в PySide6 kwargs-подключение
    в конструкторе QAction не поддерживается."""
    if _FLUENT_MENU:
        try:
            act = Action(icon, text, parent)
        except Exception:
            act = _plain_action(icon, text, parent)
    else:
        act = _plain_action(icon, text, parent)
    act.triggered.connect(handler)
    return act


# ===================== скругление интерфейса =====================

_ROUNDED = []          # [(weakref, радиус)] — чтобы пережить смену темы


def _apply_round(widget, radius):
    ss = widget.styleSheet()
    if '/*rounded*/' in ss:
        return
    widget.setStyleSheet(ss + f'\n/*rounded*/border-radius: {radius}px;')


def round_corners(widget, radius=8):
    """Скруглённые углы. Совместимо со старыми и новыми qfluentwidgets."""
    if hasattr(widget, 'setBorderRadius'):
        try:
            widget.setBorderRadius(radius)
            return
        except Exception:
            pass
    _ROUNDED.append((weakref.ref(widget), radius))
    _apply_round(widget, radius)


def reapply_rounding():
    """qfluentwidgets перезаписывает стили при смене темы — наводим заново."""
    alive = []
    for ref, radius in _ROUNDED:
        w = ref()
        if w is not None:
            alive.append((ref, radius))
            _apply_round(w, radius)
    _ROUNDED[:] = alive


# ===================== осциллограмма =====================

class Waveform(QWidget):
    """Мини-осциллограмма с индикатором прогресса."""
    BARS = 96

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(36)
        self._bars = []
        self._progress = 0.0
        if data is not None and len(data):
            mono = np.abs(data).mean(axis=1)
            chunks = np.array_split(mono, min(self.BARS, len(mono)))
            peaks = [float(c.max()) if len(c) else 0.0 for c in chunks]
            peak = max(peaks) or 1.0
            self._bars = [min(1.0, p / peak) for p in peaks]

    def set_progress(self, p: float):
        self._progress = max(0.0, min(1.0, p))
        self.update()

    def paintEvent(self, e):
        if not self._bars:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        bw = w / len(self._bars)
        played = self._progress * len(self._bars)
        idle = QColor(255, 255, 255, 70) if isDarkTheme() else QColor(0, 0, 0, 45)
        p.setPen(Qt.NoPen)
        for i, v in enumerate(self._bars):
            bh = max(2.0, v * (h - 6))
            x = i * bw + bw * 0.18
            p.setBrush(ACCENT if i < played else idle)
            p.drawRoundedRect(QRectF(x, (h - bh) / 2, bw * 0.64, bh), 1.5, 1.5)
        p.end()


# ===================== карточка звука =====================

class SoundCard(CardWidget):
    playRequested = Signal(object)
    stopRequested = Signal(object)
    deleteRequested = Signal(object)
    hotkeyRequested = Signal(object)
    moveRequested = Signal(object)            # меню «переместить» у кнопки-папки
    menuRequested = Signal(object, object)    # контекстное меню (звук, поз.)
    volumeChanged = Signal(object, float)

    def __init__(self, sound: Sound, engine: AudioEngine, library: SoundLibrary,
                 parent=None):
        super().__init__(parent)
        self.sound = sound
        self.engine = engine
        self._playing = False
        self._press_pos = None                # drag&drop: точка нажатия
        self._suppress_click = False
        self.setFixedHeight(170)
        self.setMinimumWidth(300)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        self.nameLabel = StrongBodyLabel(sound.name, self)
        self.nameLabel.setToolTip(sound.path)
        head.addWidget(self.nameLabel, 1)
        self.catLabel = CaptionLabel('', self)
        head.addWidget(self.catLabel)
        head.addWidget(CaptionLabel(_fmt_duration(sound.duration), self))
        root.addLayout(head)
        self.set_category(library.category_name(sound))

        self.wave = Waveform(sound.data, self)
        root.addWidget(self.wave, 1)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        self.playBtn = ToolButton(FluentIcon.PLAY, self)
        self.playBtn.setFixedSize(34, 34)
        self.playBtn.setToolTip('Играть / остановить')
        self.playBtn.clicked.connect(self._toggle)
        volIcon = TransparentToolButton(FluentIcon.VOLUME, self)
        volIcon.setFixedSize(30, 30)
        self.volSlider = Slider(Qt.Horizontal, self)
        self.volSlider.setFixedWidth(84)
        self.volSlider.setRange(0, 100)
        self.volSlider.setValue(int(round(sound.volume * 100)))
        self.volSlider.valueChanged.connect(
            lambda v: self.volumeChanged.emit(self.sound, v / 100))
        self.moveBtn = TransparentToolButton(FluentIcon.FOLDER, self)
        self.moveBtn.setFixedSize(30, 30)
        self.moveBtn.setToolTip('Переместить в директорию\n'
                                '(или просто перетащите карточку)')
        self.moveBtn.clicked.connect(lambda: self.moveRequested.emit(self.sound))
        self.hotkeyBtn = PushButton(FluentIcon.EDIT, sound.hotkey or 'Хоткей', self)
        self.hotkeyBtn.setFixedHeight(32)
        self.hotkeyBtn.setToolTip('Назначить глобальную горячую клавишу')
        self.hotkeyBtn.clicked.connect(lambda: self.hotkeyRequested.emit(self.sound))
        delBtn = TransparentToolButton(FluentIcon.DELETE, self)
        delBtn.setFixedSize(30, 30)
        delBtn.setToolTip('Удалить')
        delBtn.clicked.connect(lambda: self.deleteRequested.emit(self.sound))
        ctrl.addWidget(self.playBtn)
        ctrl.addSpacing(4)
        ctrl.addWidget(volIcon)
        ctrl.addWidget(self.volSlider)
        ctrl.addStretch(1)
        ctrl.addWidget(self.moveBtn)
        ctrl.addWidget(self.hotkeyBtn)
        ctrl.addWidget(delBtn)
        root.addLayout(ctrl)

        self.clicked.connect(self._toggle)     # клик по карточке = играть

        self._timer = QTimer(self)
        self._timer.setInterval(33)            # ~30 FPS прогресса
        self._timer.timeout.connect(self._tick)

        engine.playbackStarted.connect(self._on_started)
        engine.playbackFinished.connect(self._on_finished)

        round_corners(self, 14)
        round_corners(self.playBtn, 9)
        round_corners(self.moveBtn, 9)
        round_corners(self.hotkeyBtn, 9)
        round_corners(delBtn, 9)

    # ---------- воспроизведение ----------

    def _toggle(self, *_):
        if self._playing:
            self.stopRequested.emit(self.sound)
        else:
            self.playRequested.emit(self.sound)

    def _on_started(self, sid):
        if sid == self.sound.id:
            self._playing = True
            self.playBtn.setIcon(FluentIcon.PAUSE)
            self._timer.start()

    def _on_finished(self, sid):
        if sid == self.sound.id:
            self._playing = False
            self.playBtn.setIcon(FluentIcon.PLAY)
            self._timer.stop()
            self.wave.set_progress(0.0)

    def _tick(self):
        self.wave.set_progress(self.engine.position(self.sound.id))
        if not self.engine.is_playing(self.sound.id):
            self._on_finished(self.sound.id)

    # ---------- внешний вид ----------

    def set_name(self, name):
        self.nameLabel.setText(name)

    def set_hotkey(self, combo):
        self.hotkeyBtn.setText(combo or 'Хоткей')

    def set_category(self, name):
        if name:
            c = _cat_color(name)
            self.catLabel.setText(name)
            self.catLabel.setStyleSheet(
                f'background:{c.name()};border-radius:8px;'
                f'padding:1px 8px;color:white;')
            self.catLabel.show()
        else:
            self.catLabel.hide()

    # ---------- drag&drop ----------

    def mousePressEvent(self, e):
        self._press_pos = e.position().toPoint() if e.button() == Qt.LeftButton \
            else None
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self._press_pos is not None and (e.buttons() & Qt.LeftButton)
                and (e.position().toPoint() - self._press_pos)
                .manhattanLength() >= 12):
            pos, self._press_pos = self._press_pos, None
            self._suppress_click = True       # после дропа клик не запустит звук
            self._start_drag(pos)
            self._suppress_click = False
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._suppress_click:
            self._suppress_click = False
            self._press_pos = None
            e.accept()
            return
        self._press_pos = None
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e):
        self.menuRequested.emit(self.sound, e.globalPos())
        e.accept()

    def _start_drag(self, press_pos):
        mime = QMimeData()
        mime.setData(MIME_SOUND, self.sound.id.encode('utf-8'))
        drag = QDrag(self)
        drag.setMimeData(mime)

        pm = self.grab()
        if pm.width() > 260:
            pm = pm.scaledToWidth(260, Qt.SmoothTransformation)
        faded = QPixmap(pm.size())
        faded.fill(Qt.transparent)
        fp = QPainter(faded)
        fp.setOpacity(0.85)
        fp.drawPixmap(0, 0, pm)
        fp.end()
        drag.setPixmap(faded)

        scale = faded.width() / max(1.0, float(self.width()))
        hot = QPoint(int(press_pos.x() * scale), int(press_pos.y() * scale))
        hot.setX(max(0, min(hot.x(), faded.width() - 1)))
        hot.setY(max(0, min(hot.y(), faded.height() - 1)))
        drag.setHotSpot(hot)

        drag.exec(Qt.MoveAction)

        # drag-loop «съедает» отпускание кнопки — возвращаем карточку в норму
        if getattr(self, 'isPressed', False):
            self.isPressed = False
            self.update()


# ===================== саундбар =====================

class MiniEqualizer(QWidget):
    """Живой мини-эквалайзер для саундбара."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 44)
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._timer.start()
        self.update()

    def stop(self):
        self._timer.stop()

    def _tick(self):
        self._t += 0.9
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        g = QLinearGradient(QPointF(0, 0), QPointF(w, h))
        g.setColorAt(0.0, QColor('#4aa8ff'))
        g.setColorAt(1.0, ACCENT)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QRectF(2, 2, w - 4, h - 4))
        bw, gap = 4, 3
        total = 3 * bw + 2 * gap
        x = (w - total) / 2
        p.setBrush(QColor(255, 255, 255, 235))
        for i in range(3):
            k = abs(math.sin(self._t + i * 1.1))
            bh = 8 + k * 16
            p.drawRoundedRect(QRectF(x, (h - bh) / 2, bw, bh), bw / 2, bw / 2)
            x += bw + gap
        p.end()


class SoundBar(QWidget):
    """Плавающая панель текущего звука: выезжает снизу, есть перелистывание."""
    volumeChanged = Signal(str, float)      # id звука, громкость
    prevRequested = Signal()
    nextRequested = Signal()
    BAR_H = 64                              # видимая высота карточки
    MARGIN = 10                             # поля под тень

    def __init__(self, page: QWidget, engine: AudioEngine):
        super().__init__(page)
        self._engine = engine
        self._sound = None
        self._slide = 0.0
        self._progress = 0.0
        self._hidden_by_user = False
        self.setFixedHeight(self.BAR_H + 2 * self.MARGIN)
        self.hide()

        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._set_slide)
        self._anim.finished.connect(self._on_anim_finished)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(self.MARGIN + 8, self.MARGIN,
                               self.MARGIN + 8, self.MARGIN + 8)
        lay.setSpacing(10)

        self.eq = MiniEqualizer(self)
        lay.addWidget(self.eq)

        text = QVBoxLayout()
        text.setSpacing(1)
        self.titleLabel = StrongBodyLabel('', self)
        self.posLabel = CaptionLabel('', self)
        text.addWidget(self.titleLabel)
        text.addWidget(self.posLabel)
        lay.addLayout(text, 1)

        self.prevBtn = TransparentToolButton(
            ficon('CARE_LEFT_SOLID', 'LEFT_ARROW'), self)
        self.prevBtn.setFixedSize(30, 30)
        self.prevBtn.setToolTip('Предыдущий звук')
        self.prevBtn.clicked.connect(self.prevRequested.emit)
        self.nextBtn = TransparentToolButton(
            ficon('CARE_RIGHT_SOLID', 'RIGHT_ARROW'), self)
        self.nextBtn.setFixedSize(30, 30)
        self.nextBtn.setToolTip('Следующий звук')
        self.nextBtn.clicked.connect(self.nextRequested.emit)
        lay.addWidget(self.prevBtn)
        lay.addWidget(self.nextBtn)

        volIcon = TransparentToolButton(FluentIcon.VOLUME, self)
        volIcon.setFixedSize(30, 30)
        self.volSlider = Slider(Qt.Horizontal, self)
        self.volSlider.setFixedWidth(90)
        self.volSlider.setRange(0, 100)
        self.volSlider.valueChanged.connect(self._on_volume)
        self.stopBtn = ToolButton(FluentIcon.PAUSE, self)
        self.stopBtn.setFixedSize(36, 36)
        self.stopBtn.setToolTip('Остановить')
        self.stopBtn.clicked.connect(self._stop_current)
        self.closeBtn = TransparentToolButton(FluentIcon.CLOSE, self)
        self.closeBtn.setFixedSize(30, 30)
        self.closeBtn.setToolTip('Скрыть панель (звук продолжит играть)')
        self.closeBtn.clicked.connect(self._user_hide)
        lay.addWidget(volIcon)
        lay.addWidget(self.volSlider)
        lay.addWidget(self.stopBtn)
        lay.addWidget(self.closeBtn)

        round_corners(self.prevBtn, 9)
        round_corners(self.nextBtn, 9)
        round_corners(self.stopBtn, 9)
        round_corners(self.closeBtn, 9)

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)

    # ---------- публичное ----------

    def show_for(self, sound: Sound):
        if sound is None or sound.data is None:
            return
        self._sound = sound
        self._hidden_by_user = False
        self._progress = 0.0
        self.titleLabel.setText(sound.name)
        self.posLabel.setText(
            f'{_fmt_time(0)} / {_fmt_time(sound.duration)}')
        self.volSlider.blockSignals(True)
        self.volSlider.setValue(int(round(sound.volume * 100)))
        self.volSlider.blockSignals(False)
        self.show()
        self.raise_()
        self._apply_pos()
        self.eq.start()
        self._timer.start()
        self._animate(1.0)

    def notify_finished(self, sound_id):
        if (self._sound is not None and self._sound.id == sound_id
                and not self._hidden_by_user):
            self._animate(0.0)

    def current_sound(self):
        return self._sound

    def reposition(self):
        self._apply_pos()

    # ---------- внутреннее ----------

    def _animate(self, target):
        self._anim.stop()
        self._anim.setStartValue(float(self._slide))
        self._anim.setEndValue(float(target))
        self._anim.setDuration(340 if target > self._slide else 280)
        self._anim.setEasingCurve(
            QEasingCurve.OutCubic if target > self._slide
            else QEasingCurve.InCubic)
        self._anim.start()

    def _set_slide(self, v):
        self._slide = float(v)
        self._apply_pos()

    def _apply_pos(self):
        p = self.parentWidget()
        if p is None:
            return
        w = max(430, min(700, p.width() - 32))
        x = (p.width() - w) // 2
        y_final = p.height() - self.height() - 12
        y_start = p.height() - 2
        if self.width() != w:
            self.resize(w, self.height())
        self.move(x, int(y_start + (y_final - y_start) * self._slide))

    def _on_anim_finished(self):
        if self._slide <= 0.01:
            self.hide()
            self._timer.stop()
            self.eq.stop()

    def _tick(self):
        s = self._sound
        if s is None:
            return
        if self._engine.is_playing(s.id):
            self._progress = self._engine.position(s.id)
            self.posLabel.setText(
                f'{_fmt_time(self._progress * s.duration)} / '
                f'{_fmt_time(s.duration)}')
        self.update()

    def _stop_current(self):
        if self._sound is not None:
            self._engine.stop(self._sound.id)

    def _user_hide(self):
        self._hidden_by_user = True
        self._animate(0.0)

    def _on_volume(self, v):
        if self._sound is not None:
            self._sound.volume = v / 100.0
            self.volumeChanged.emit(self._sound.id, v / 100.0)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        m = float(self.MARGIN)
        dark = isDarkTheme()
        card = QRectF(m, m, w - 2 * m, h - 2 * m)
        path = QPainterPath()
        path.addRoundedRect(card, 14, 14)

        p.setPen(Qt.NoPen)                            # мягкая тень
        for i in range(1, 5):
            a = 22 - i * 4
            p.setBrush(QColor(0, 0, 0, a if dark else max(4, a // 2)))
            p.drawRoundedRect(card.adjusted(-i * 1.4, -i * 0.6,
                                            i * 1.4, i * 1.6), 18, 18)

        p.fillPath(path, QBrush(QColor('#24262e') if dark
                                else QColor('#ffffff')))   # карточка
        p.setPen(QPen(QColor(255, 255, 255, 36) if dark
                      else QColor(0, 0, 0, 26), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(card, 14, 14)

        if self._progress > 0.003:                    # полоска прогресса
            pad, bh = 10.0, 3.0
            bw = (card.width() - 2 * pad) * self._progress
            p.setPen(Qt.NoPen)
            p.setBrush(ACCENT)
            p.setClipPath(path)
            p.drawRoundedRect(QRectF(card.left() + pad,
                                     card.bottom() - pad * 0.5 - bh,
                                     max(bw, bh * 2), bh), bh / 2, bh / 2)
        p.end()


# ===================== кнопка директории =====================

class CategoryButton(QWidget):
    """Пункт списка директорий: аватар-буква, название, счётчик.
    Принимает перетаскиваемые звуки и файлы из проводника."""
    clicked = Signal()
    contextRequested = Signal(object)      # глобальная позиция правого клика
    dropRequested = Signal(str)            # id перетащенного звука
    filesDropped = Signal(list)            # url файлов из проводника

    def __init__(self, avatar, title, color=None, droppable=False, parent=None):
        super().__init__(parent)
        self._avatar = avatar
        self._title = title
        self._color = color or QColor('#0078d4')
        self._count = 0
        self._selected = False
        self._hover = False
        self._drop_hover = False
        self._droppable = bool(droppable)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(40)
        if self._droppable:
            self.setAcceptDrops(True)

    def set_selected(self, v):
        self._selected = bool(v)
        self.update()

    def set_count(self, n):
        self._count = n
        self.update()

    def set_title(self, t):
        self._title = t
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self._drop_hover = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.contextRequested.emit(e.globalPosition().toPoint())
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and \
                self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
            e.accept()
        else:
            super().mouseReleaseEvent(e)

    # ---------- приём drag&drop ----------

    def _can_handle(self, md):
        return self._droppable and (md.hasFormat(MIME_SOUND) or md.hasUrls())

    def dragEnterEvent(self, e):
        if self._can_handle(e.mimeData()):
            e.acceptProposedAction()
            self._drop_hover = True
            self.update()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if self._can_handle(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self._drop_hover = False
        self.update()
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self._drop_hover = False
        self.update()
        md = e.mimeData()
        if not self._droppable:
            e.ignore()
            return
        if md.hasFormat(MIME_SOUND):
            sid = bytes(md.data(MIME_SOUND)).decode('utf-8')
            e.acceptProposedAction()
            self.dropRequested.emit(sid)
        elif md.hasUrls():
            e.acceptProposedAction()
            self.filesDropped.emit(md.urls())
        else:
            e.ignore()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        dark = isDarkTheme()

        p.setPen(Qt.NoPen)
        if self._drop_hover:                     # цель перетаскивания
            p.setBrush(QColor(0, 120, 212, 110 if dark else 80))
            p.drawRoundedRect(QRectF(2, 2, w - 4, h - 4), 8, 8)
        elif self._selected:
            p.setBrush(QColor(0, 120, 212, 72 if dark else 44))
            p.drawRoundedRect(QRectF(2, 2, w - 4, h - 4), 8, 8)
        elif self._hover:
            p.setBrush(QColor(255, 255, 255, 30) if dark
                       else QColor(0, 0, 0, 22))
            p.drawRoundedRect(QRectF(2, 2, w - 4, h - 4), 8, 8)

        if self._drop_hover:
            p.setPen(QPen(ACCENT, 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(2.5, 2.5, w - 5, h - 5), 7, 7)
            p.setPen(Qt.NoPen)

        d, ax = 26.0, 12.0                       # аватар
        p.setBrush(self._color)
        p.drawEllipse(QRectF(ax, (h - d) / 2, d, d))
        f = p.font()
        f.setBold(True)
        f.setPointSize(11)
        p.setFont(f)
        p.setPen(Qt.white)
        p.drawText(QRectF(ax, (h - d) / 2, d, d), Qt.AlignCenter, self._avatar)

        f.setBold(False)                         # название
        f.setPointSize(10)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 235) if dark else QColor(0, 0, 0, 215))
        tx = ax + d + 10
        avail = w - tx - 12 - (32 if self._count else 0)
        txt = p.fontMetrics().elidedText(self._title, Qt.ElideRight,
                                         max(10, int(avail)))
        p.drawText(QRectF(tx, 0, avail, h), Qt.AlignVCenter | Qt.AlignLeft, txt)

        if self._count:                          # счётчик
            f.setPointSize(9)
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, 140) if dark
                     else QColor(0, 0, 0, 140))
            p.drawText(QRectF(w - 12 - 30, 0, 30, h),
                       Qt.AlignVCenter | Qt.AlignRight, str(self._count))
        p.end()


# ===================== диалоги =====================

class NameDialog(MessageBoxBase):
    """Диалог ввода названия — для директорий и звуков."""

    def __init__(self, title, current='', placeholder='Название', parent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel(title, self))
        self.edit = LineEdit(self)
        self.edit.setText(current)
        self.edit.setPlaceholderText(placeholder)
        self.edit.returnPressed.connect(self.accept)
        self.viewLayout.addWidget(self.edit)
        self.yesButton.setText('Сохранить')
        self.cancelButton.setText('Отмена')
        round_corners(self.edit, 8)
        round_corners(self.yesButton, 8)
        round_corners(self.cancelButton, 8)

    def showEvent(self, e):
        super().showEvent(e)
        self.edit.setFocus()
        self.edit.selectAll()


class AddSoundDialog(MessageBoxBase):
    """Диалог при добавлении звука: название + директория."""

    def __init__(self, name, library: SoundLibrary, default_cat=None,
                 parent=None):
        super().__init__(parent)
        self._ids = [None]                       # индексы комбобокса -> id

        self.viewLayout.addWidget(SubtitleLabel('Добавить звук', self))
        self.viewLayout.addWidget(CaptionLabel('Задайте название и выберите '
                                               'директорию.', self))
        self.viewLayout.addWidget(BodyLabel('Название', self))
        self.nameEdit = LineEdit(self)
        self.nameEdit.setText(name)
        self.nameEdit.setPlaceholderText('Название звука')
        self.nameEdit.returnPressed.connect(self.accept)
        self.viewLayout.addWidget(self.nameEdit)
        self.viewLayout.addWidget(BodyLabel('Директория', self))

        self.catCombo = ComboBox(self)
        self.catCombo.addItem('Без директории')
        for c in library.categories:
            self.catCombo.addItem(c.name)
            self._ids.append(c.id)
        if default_cat is not None and default_cat in self._ids:
            self.catCombo.setCurrentIndex(self._ids.index(default_cat))
        self.viewLayout.addWidget(self.catCombo)

        self.yesButton.setText('Добавить')
        self.cancelButton.setText('Отмена')
        round_corners(self.nameEdit, 8)
        round_corners(self.catCombo, 8)
        round_corners(self.yesButton, 8)
        round_corners(self.cancelButton, 8)

    def category_id(self):
        return self._ids[self.catCombo.currentIndex()]

    def showEvent(self, e):
        super().showEvent(e)
        self.nameEdit.setFocus()
        self.nameEdit.selectAll()


class HotkeyDialog(MessageBoxBase):
    _captured = Signal(str)

    def __init__(self, current='', hotkeys: HotkeyManager = None, parent=None):
        super().__init__(parent)
        self.combo = current or ''
        self._pressed = []
        self._hook = None
        self._hotkeys = hotkeys
        self._captured.connect(self._show)

        title = SubtitleLabel('Горячая клавиша', self)
        self.edit = LineEdit(self)
        self.edit.setReadOnly(True)
        self.edit.setText(self.combo)
        self.edit.setPlaceholderText(
            'Нажмите комбинацию…' if keyboard else 'Модуль keyboard недоступен')
        hint = CaptionLabel('Например: Ctrl+F1. Работает глобально, '
                            'даже когда окно свёрнуто.', self)
        hint.setWordWrap(True)
        clearBtn = PushButton('Убрать хоткей', self)
        clearBtn.clicked.connect(self._clear)

        self.viewLayout.addWidget(title)
        self.viewLayout.addWidget(self.edit)
        self.viewLayout.addWidget(hint)
        self.viewLayout.addWidget(clearBtn, 0, Qt.AlignLeft)
        self.yesButton.setText('Сохранить')
        self.cancelButton.setText('Отмена')

        round_corners(self.edit, 8)
        round_corners(self.yesButton, 8)
        round_corners(self.cancelButton, 8)
        round_corners(clearBtn, 8)

    def _clear(self):
        self.combo = ''
        self.edit.clear()
        self.accept()

    def showEvent(self, e):
        super().showEvent(e)
        if self._hotkeys:
            self._hotkeys.suspend()       # чтобы назначение не запускало звуки
        if keyboard is not None and self._hook is None:
            try:
                self._hook = keyboard.hook(self._on_key, suppress=False)
            except Exception:
                self._hook = None
                self.edit.setPlaceholderText('Хоткеи недоступны в этой системе')

    def hideEvent(self, e):
        if self._hook is not None:
            try:
                keyboard.unhook(self._hook)
            except Exception:
                pass
            self._hook = None
        if self._hotkeys:
            self._hotkeys.resume()
        super().hideEvent(e)

    def _on_key(self, event):
        try:
            if event.event_type == 'down':
                name = (event.name or '').lower()
                if name and name not in self._pressed:
                    self._pressed.append(name)
            elif event.event_type == 'up' and self._pressed:
                keys, self._pressed = self._pressed, []
                combo = self._build(keys)
                if combo:
                    self._captured.emit(combo)   # потокобезопасно через сигнал
        except Exception:
            pass

    @staticmethod
    def _build(keys):
        mods = [k for k in keys if k in MODS]
        normal = [k for k in keys if k not in MODS]
        if not normal:
            return ''
        parts = []
        for m in ('ctrl', 'alt', 'shift', 'windows'):
            if any(m in k for k in mods):
                parts.append(m)
        parts.append(normal[-1])
        return '+'.join(parts)

    def _show(self, combo):
        self.combo = combo
        self.edit.setText(combo)


# ===================== страница «Звуки» =====================

class SoundboardPage(QWidget):
    CARD_W = 340

    def __init__(self, engine, library, hotkeys, parent=None):
        super().__init__(parent)
        self.setObjectName('soundboard-page')
        self.engine = engine
        self.library = library
        self.hotkeys = hotkeys
        self.cards = {}
        self.cat_buttons = {}
        self.current_category = 'all'      # 'all' | 'none' | id директории

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        top = QHBoxLayout()
        self.search = SearchLineEdit(self)
        self.search.setPlaceholderText('Поиск по названию…')
        self.search.setFixedWidth(280)
        self.search.textChanged.connect(lambda _: self._refilter())
        addBtn = PrimaryPushButton(FluentIcon.ADD, 'Добавить звуки', self)
        addBtn.clicked.connect(self._pick_files)
        top.addWidget(self.search)
        top.addStretch(1)
        top.addWidget(addBtn)
        root.addLayout(top)
        round_corners(self.search, 8)
        round_corners(addBtn, 8)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        # ---- панель директорий ----
        self.catPanel = QWidget(self)
        self.catPanel.setFixedWidth(210)
        catLay = QVBoxLayout(self.catPanel)
        catLay.setContentsMargins(0, 0, 0, 0)
        catLay.setSpacing(4)
        catLay.addWidget(BodyLabel('Директории', self.catPanel))
        self.catList = QVBoxLayout()
        self.catList.setSpacing(2)
        catLay.addLayout(self.catList, 1)
        hint = CaptionLabel('Перетащите звук на директорию, '
                            'чтобы переместить его', self.catPanel)
        hint.setWordWrap(True)
        catLay.addWidget(hint)
        self.newCatBtn = PushButton(FluentIcon.ADD, 'Новая директория',
                                    self.catPanel)
        self.newCatBtn.clicked.connect(self._create_category)
        catLay.addWidget(self.newCatBtn)
        body.addWidget(self.catPanel)

        # ---- сетка карточек ----
        content = QVBoxLayout()
        content.setSpacing(0)
        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        try:
            self.scroll.enableTransparentBackground()
        except AttributeError:
            self.scroll.setStyleSheet(
                'QScrollArea{background:transparent;border:none}'
                ' QScrollArea>QWidget>QWidget{background:transparent}')
        self.container = QWidget(self)
        self.grid = QGridLayout(self.container)
        self.grid.setContentsMargins(4, 0, 4, 4)
        self.grid.setSpacing(12)
        self.scroll.setWidget(self.container)
        content.addWidget(self.scroll, 1)

        self.emptyLabel = BodyLabel('Здесь пока нет звуков.\nДобавьте их кнопкой '
                                    '«Добавить звуки» или перетащите файлы\n'
                                    'в окно — или сразу на нужную директорию.', self)
        self.emptyLabel.setAlignment(Qt.AlignCenter)
        content.addWidget(self.emptyLabel, 1)
        body.addLayout(content, 1)

        # ---- саундбар ----
        self.soundbar = SoundBar(self, self.engine)
        self.soundbar.volumeChanged.connect(self._sync_volume)
        self.soundbar.nextRequested.connect(lambda: self._shift_soundbar(1))
        self.soundbar.prevRequested.connect(lambda: self._shift_soundbar(-1))
        self.engine.playbackStarted.connect(self._on_playback_started)
        self.engine.playbackFinished.connect(self._on_playback_finished)

        for s in self.library.sounds:
            self._add_card(s)
        self._rebuild_categories()
        self._refilter()

    # ---------- карточки ----------

    def _add_card(self, sound):
        card = SoundCard(sound, self.engine, self.library, self)
        card.playRequested.connect(self._play)
        card.stopRequested.connect(self._stop)
        card.deleteRequested.connect(self._delete)
        card.hotkeyRequested.connect(self._assign_hotkey)
        card.menuRequested.connect(self._sound_menu)
        card.moveRequested.connect(
            lambda s, c=card: self._move_menu(s, c.moveBtn))
        card.volumeChanged.connect(self._volume)
        self.cards[sound.id] = card

    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, 'Добавить звуки', str(Path.home()),
            'Аудио (*.wav *.mp3 *.flac *.ogg *.oga *.opus)')
        added = 0
        for f in files:
            if self.add_sound_interactive(f):    # диалог: имя + директория
                added += 1
        if added:
            InfoBar.success('Добавлено', f'Новых звуков: {added}',
                            parent=self.window(), position=InfoBarPosition.TOP)

    # ---------- добавление звуков ----------

    def add_sound_interactive(self, path) -> bool:
        """Добавление с диалогом: название + директория."""
        path = str(path)
        if Path(path).suffix.lower() not in AUDIO_EXTS:
            return False
        if any(s.path == path for s in self.library.sounds):
            InfoBar.warning('Дубликат', f'«{Path(path).name}» уже в библиотеке.',
                            parent=self.window(), position=InfoBarPosition.TOP)
            return False
        sound = Sound(path)
        try:
            sound.load()
        except Exception as err:
            InfoBar.error('Ошибка', f'Не удалось открыть {Path(path).name}: {err}',
                          parent=self.window(), position=InfoBarPosition.TOP,
                          duration=4000)
            return False
        default_cat = None
        if (self.current_category not in ('all', 'none')
                and self.library.category(self.current_category) is not None):
            default_cat = self.current_category
        dlg = AddSoundDialog(sound.name, self.library, default_cat, self.window())
        if not dlg.exec():
            return False                        # отмена — пропускаем файл
        name = dlg.nameEdit.text().strip()
        if name:
            sound.name = name
        sound.category = dlg.category_id()
        self._register_sound(sound)
        return True

    def add_sound_file(self, path, category=None) -> bool:
        """Тихое добавление (без диалога) — для drop'а на конкретную директорию."""
        path = str(path)
        if Path(path).suffix.lower() not in AUDIO_EXTS:
            return False
        if any(s.path == path for s in self.library.sounds):
            InfoBar.warning('Дубликат', f'«{Path(path).name}» уже в библиотеке.',
                            parent=self.window(), position=InfoBarPosition.TOP)
            return False
        sound = Sound(path)
        try:
            sound.load()
        except Exception as err:
            InfoBar.error('Ошибка', f'Не удалось открыть {Path(path).name}: {err}',
                          parent=self.window(), position=InfoBarPosition.TOP,
                          duration=4000)
            return False
        sound.category = category
        self._register_sound(sound)
        return True

    def _register_sound(self, sound):
        self.library.add(sound)
        self.library.save()
        self._add_card(sound)
        self._refresh_counts()
        self._refilter()

    def _add_files_to(self, urls, cid):
        """Файлы из проводника бросили прямо на директорию."""
        added = 0
        for url in urls:
            if url.isLocalFile() and self.add_sound_file(url.toLocalFile(),
                                                         category=cid):
                added += 1
        if added:
            cat = self.library.category(cid)
            name = cat.name if cat else 'Без директории'
            InfoBar.success('Добавлено', f'{added} — в «{name}»',
                            parent=self.window(), position=InfoBarPosition.TOP)

    def _play(self, sound):
        self.engine.play(sound)

    def _stop(self, sound):
        self.engine.stop(sound.id)

    def _volume(self, sound, value):
        sound.volume = value

    def _sync_volume(self, sound_id, value):
        card = self.cards.get(sound_id)
        if card is not None:
            card.volSlider.blockSignals(True)
            card.volSlider.setValue(int(round(value * 100)))
            card.volSlider.blockSignals(False)

    def _delete(self, sound):
        box = MessageBox('Удалить звук?',
                         f'«{sound.name}» будет убран из библиотеки.',
                         self.window())
        round_corners(box.yesButton, 8)
        round_corners(box.cancelButton, 8)
        if not box.exec():
            return
        self.engine.stop(sound.id)
        self.hotkeys.unbind(sound.id)
        self.library.remove(sound)
        self.library.save()
        card = self.cards.pop(sound.id, None)
        if card:
            card.setParent(None)
            card.deleteLater()
        self._refresh_counts()
        self._refilter()

    def _rename_sound(self, sound):
        dlg = NameDialog('Переименовать звук', sound.name, 'Название звука',
                         self.window())
        if not dlg.exec():
            return
        name = dlg.edit.text().strip()
        if not name:
            return
        sound.name = name
        self.library.save()
        card = self.cards.get(sound.id)
        if card:
            card.set_name(name)

    def _assign_hotkey(self, sound):
        dlg = HotkeyDialog(sound.hotkey, self.hotkeys, self.window())
        if not dlg.exec():
            return
        combo = dlg.combo.strip()
        if combo and combo != sound.hotkey:
            for other in self.library.sounds:      # уникальность хоткеев
                if other is not sound and other.hotkey == combo:
                    other.hotkey = None
                    self.hotkeys.unbind(other.id)
                    oc = self.cards.get(other.id)
                    if oc:
                        oc.set_hotkey(None)
        sound.hotkey = combo or None
        if not self.hotkeys.bind(sound.id, sound.hotkey):
            sound.hotkey = None
            InfoBar.error('Хоткей', f'Не удалось назначить «{combo}».',
                          parent=self.window(), position=InfoBarPosition.TOP)
        card = self.cards.get(sound.id)
        if card:
            card.set_hotkey(sound.hotkey)
        self.library.save()

    # ---------- перемещение между директориями и по порядку ----------

    def _move_sound_id(self, sound_id, cid):
        sound = self.library.get(sound_id)
        if sound is None or sound.category == cid:
            return
        sound.category = cid
        self.library.save()
        card = self.cards.get(sound_id)
        if card:
            card.set_category(self.library.category_name(sound))
        self._refresh_counts()
        self._refilter()
        cat = self.library.category(cid)
        dest = cat.name if cat else 'Без директории'
        InfoBar.success('Перемещено', f'«{sound.name}» → «{dest}»',
                        parent=self.window(), position=InfoBarPosition.TOP,
                        duration=2200)

    def _move_menu(self, sound, btn):
        menu = make_menu(self)
        menu.addAction(menu_action(ficon('MINUS', FluentIcon.CLOSE),
                                   'Без директории',
                                   lambda: self._move_sound_id(sound.id, None)))
        for cat in self.library.categories:
            menu.addAction(menu_action(FluentIcon.FOLDER, cat.name,
                                       lambda c=cat.id:
                                       self._move_sound_id(sound.id, c)))
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _move_sound_order(self, sound, delta):
        """Сдвиг звука по порядку: к соседнему видимому звуку."""
        sounds = self.library.sounds
        try:
            i = sounds.index(sound)
        except ValueError:
            return
        step = 1 if delta > 0 else -1
        target = None
        k = i + step
        while 0 <= k < len(sounds):
            if self._is_visible(sounds[k]):
                target = k
                break
            k += step
        if target is None:
            # видимого соседа нет — двигаем на соседнюю позицию глобально
            target = i + step
            if not (0 <= target < len(sounds)):
                return
        if self.library.reorder_sound(sound, target):
            self.library.save()
            self._resort_cards()
            self._relayout()

    def _sound_menu(self, sound, global_pos):
        menu = make_menu(self)
        playing = self.engine.is_playing(sound.id)
        if playing:
            menu.addAction(menu_action(FluentIcon.PAUSE, 'Остановить',
                                       lambda: self._stop(sound)))
        else:
            menu.addAction(menu_action(FluentIcon.PLAY, 'Играть',
                                       lambda: self._play(sound)))
        menu.addAction(menu_action(FluentIcon.EDIT, 'Переименовать',
                                   lambda: self._rename_sound(sound)))
        menu.addSeparator()
        if self.library.categories:
            for cat in self.library.categories:
                menu.addAction(menu_action(FluentIcon.FOLDER, cat.name,
                                           lambda c=cat.id:
                                           self._move_sound_id(sound.id, c)))
            menu.addAction(menu_action(ficon('MINUS', FluentIcon.CLOSE),
                                       'Без директории',
                                       lambda: self._move_sound_id(sound.id,
                                                                   None)))
            menu.addSeparator()
        menu.addAction(menu_action(ficon('CARE_UP_SOLID', 'ARROW_UP'),
                                   'Выше',
                                   lambda: self._move_sound_order(sound, -1)))
        menu.addAction(menu_action(ficon('CARE_DOWN_SOLID', 'ARROW_DOWN'),
                                   'Ниже',
                                   lambda: self._move_sound_order(sound, 1)))
        menu.addSeparator()
        menu.addAction(menu_action(FluentIcon.EDIT, 'Горячая клавиша',
                                   lambda: self._assign_hotkey(sound)))
        menu.addAction(menu_action(FluentIcon.DELETE, 'Удалить',
                                   lambda: self._delete(sound)))
        menu.exec(global_pos)

    # ---------- директории ----------

    def _clear_layout(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

    def _rebuild_categories(self):
        self._clear_layout(self.catList)
        self.cat_buttons.clear()

        all_btn = CategoryButton('♪', 'Все звуки', QColor('#0078d4'))
        all_btn.clicked.connect(lambda: self._select_category('all'))
        self.catList.addWidget(all_btn)
        self.cat_buttons['all'] = all_btn

        none_btn = CategoryButton('•', 'Без директории', QColor('#8a8f98'),
                                  droppable=True)
        none_btn.clicked.connect(lambda: self._select_category('none'))
        none_btn.dropRequested.connect(
            lambda sid: self._move_sound_id(sid, None))
        none_btn.filesDropped.connect(
            lambda urls: self._add_files_to(urls, None))
        self.catList.addWidget(none_btn)
        self.cat_buttons['none'] = none_btn

        for cat in self.library.categories:
            btn = CategoryButton(cat.name[:1].upper() or '?', cat.name,
                                 _cat_color(cat.name), droppable=True)
            btn.clicked.connect(lambda c=cat.id: self._select_category(c))
            btn.contextRequested.connect(
                lambda pos, c=cat.id: self._category_menu(c, pos))
            btn.dropRequested.connect(
                lambda sid, c=cat.id: self._move_sound_id(sid, c))
            btn.filesDropped.connect(
                lambda urls, c=cat.id: self._add_files_to(urls, c))
            self.catList.addWidget(btn)
            self.cat_buttons[cat.id] = btn

        self.catList.addStretch(1)
        self._refresh_counts()
        self._update_selected_cat()

    def _select_category(self, key):
        self.current_category = key
        self._update_selected_cat()
        self._refilter()

    def _update_selected_cat(self):
        for k, b in self.cat_buttons.items():
            b.set_selected(k == self.current_category)

    def _refresh_counts(self):
        counts = {'all': len(self.library.sounds), 'none': 0}
        for s in self.library.sounds:
            if s.category is None:
                counts['none'] += 1
            else:
                counts[s.category] = counts.get(s.category, 0) + 1
        for k, b in self.cat_buttons.items():
            b.set_count(counts.get(k, 0))

    def _create_category(self):
        dlg = NameDialog('Новая директория', '', 'Название директории',
                         self.window())
        if not dlg.exec():
            return
        name = dlg.edit.text().strip()
        if not name:
            return
        cat = self.library.add_category(name)
        self.library.save()
        self._rebuild_categories()
        self._select_category(cat.id)
        InfoBar.success('Директория', f'«{name}» создана',
                        parent=self.window(), position=InfoBarPosition.TOP)

    def _category_menu(self, cid, global_pos):
        if self.library.category(cid) is None:
            return
        menu = make_menu(self)
        menu.addAction(menu_action(ficon('CARE_UP_SOLID', 'ARROW_UP'), 'Вверх',
                                   lambda: self._move_category_order(cid, -1)))
        menu.addAction(menu_action(ficon('CARE_DOWN_SOLID', 'ARROW_DOWN'),
                                   'Вниз',
                                   lambda: self._move_category_order(cid, 1)))
        menu.addSeparator()
        menu.addAction(menu_action(FluentIcon.EDIT, 'Переименовать',
                                   lambda: self._rename_category(cid)))
        menu.addAction(menu_action(FluentIcon.DELETE, 'Удалить',
                                   lambda: self._delete_category(cid)))
        menu.exec(global_pos)

    def _move_category_order(self, cid, delta):
        if self.library.move_category(cid, delta):
            self.library.save()
            self._rebuild_categories()

    def _rename_category(self, cid):
        cat = self.library.category(cid)
        if cat is None:
            return
        dlg = NameDialog('Переименовать директорию', cat.name,
                         'Название директории', self.window())
        if not dlg.exec():
            return
        name = dlg.edit.text().strip()
        if not name:
            return
        self.library.rename_category(cid, name)
        self.library.save()
        self._rebuild_categories()
        self._sync_card_categories()

    def _delete_category(self, cid):
        cat = self.library.category(cid)
        if cat is None:
            return
        box = MessageBox('Удалить директорию?',
                         f'«{cat.name}» будет удалена. Звуки останутся '
                         'в библиотеке — без директории.', self.window())
        round_corners(box.yesButton, 8)
        round_corners(box.cancelButton, 8)
        if not box.exec():
            return
        if self.current_category == cid:
            self.current_category = 'all'
        self.library.remove_category(cid)
        self.library.save()
        self._rebuild_categories()
        self._select_category(self.current_category)
        self._sync_card_categories()

    def _sync_card_categories(self):
        for card in self.cards.values():
            card.set_category(self.library.category_name(card.sound))

    # ---------- фильтрация и раскладка ----------

    def _match_category(self, sound):
        if self.current_category == 'all':
            return True
        if self.current_category == 'none':
            return sound.category is None
        return sound.category == self.current_category

    def _is_visible(self, sound):
        q = self.search.text().strip().lower()
        return self._match_category(sound) and \
            (not q or q in sound.name.lower())

    def _refilter(self):
        for card in self.cards.values():
            card.setVisible(self._is_visible(card.sound))
        self._update_empty()
        self._relayout()

    def _resort_cards(self):
        """Пересобираем self.cards в порядке library.sounds (порядок сетки)."""
        ordered = {}
        for s in self.library.sounds:
            card = self.cards.get(s.id)
            if card is not None:
                ordered[s.id] = card
        for sid, card in self.cards.items():      # на всякий случай — остатки
            if sid not in ordered:
                ordered[sid] = card
        self.cards = ordered

    def _update_empty(self):
        visible = any(not c.isHidden() for c in self.cards.values())
        self.scroll.setVisible(visible)
        self.emptyLabel.setVisible(not visible)

    def _relayout(self):
        cols = max(1, max(320, self.scroll.viewport().width()) // self.CARD_W)
        while self.grid.count():
            self.grid.takeAt(0)
        row = col = 0
        for card in self.cards.values():
            if card.isHidden():
                continue
            self.grid.addWidget(card, row, col)
            col += 1
            if col >= cols:
                col, row = 0, row + 1

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()
        self.soundbar.reposition()

    # ---------- саундбар: перелистывание ----------

    def _shift_soundbar(self, delta):
        playlist = [s for s in self.library.sounds if self._is_visible(s)]
        if not playlist:
            return
        cur = self.soundbar.current_sound()
        idx = -1
        if cur is not None:
            for i, s in enumerate(playlist):
                if s.id == cur.id:
                    idx = i
                    break
        if idx < 0:                              # текущего нет в списке
            new_idx = 0 if delta > 0 else len(playlist) - 1
        else:
            new_idx = (idx + delta) % len(playlist)
        target = playlist[new_idx]
        if cur is not None and cur.id != target.id:
            self.engine.stop(cur.id)
        self.engine.play(target)

    def _on_playback_started(self, sid):
        sound = self.library.get(sid)
        if sound is not None:
            self.soundbar.show_for(sound)

    def _on_playback_finished(self, sid):
        self.soundbar.notify_finished(sid)


# ===================== страница «Настройки» =====================

class SettingRowCard(CardWidget):
    def __init__(self, title, caption='', parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 12, 16, 12)
        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(BodyLabel(title, self))
        if caption:
            c = CaptionLabel(caption, self)
            c.setWordWrap(True)
            left.addWidget(c)
        h.addLayout(left, 1)
        h.addSpacing(16)

    def addWidget(self, w):
        self.layout().addWidget(w)


class SettingsPage(QWidget):
    devicesChanged = Signal(object, object)
    masterChanged = Signal(float)
    themeChanged = Signal(str)

    def __init__(self, engine, settings: Settings, parent=None):
        super().__init__(parent)
        self.setObjectName('settings-page')
        self.engine = engine
        self.settings = settings
        self._p_ids = [None]
        self._s_ids = [None]

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        root.addWidget(TitleLabel('Настройки', self))
        root.addWidget(SubtitleLabel('Воспроизведение', self))

        primary = SettingRowCard('Основное устройство',
                                 'Куда играют звуки. Для передачи в Discord/TS '
                                 'выберите CABLE Input.', self)
        self.primaryCombo = ComboBox(primary)
        primary.addWidget(self.primaryCombo)
        root.addWidget(primary)

        secondary = SettingRowCard('Дополнительное устройство',
                                   'Необязательно: например, наушники — чтобы вы '
                                   'слышали звуки сами.', self)
        self.secondaryCombo = ComboBox(secondary)
        secondary.addWidget(self.secondaryCombo)
        root.addWidget(secondary)

        master = SettingRowCard('Общая громкость', 'Действует на все звуки сразу.', self)
        self.masterSlider = Slider(Qt.Horizontal, master)
        self.masterSlider.setFixedWidth(220)
        self.masterSlider.setRange(0, 100)
        self.masterSlider.setValue(int(settings.master * 100))
        master.addWidget(self.masterSlider)
        root.addWidget(master)

        tip = CaptionLabel('Совет: установите VB-Audio Virtual Cable. Выберите '
                           '«CABLE Input» основным устройством здесь, а в Discord '
                           'микрофоном — «CABLE Output». Тогда все звуки будут '
                           'слышны в голосовом чате.', self)
        tip.setWordWrap(True)
        root.addWidget(tip)

        root.addWidget(SubtitleLabel('Внешний вид', self))
        theme = SettingRowCard('Тема', 'Оформление интерфейса.', self)
        self.themeCombo = ComboBox(theme)
        self.themeCombo.addItems(['Системная', 'Светлая', 'Тёмная'])
        self.themeCombo.setCurrentIndex(
            {'auto': 0, 'light': 1, 'dark': 2}.get(settings.theme, 0))
        theme.addWidget(self.themeCombo)
        root.addWidget(theme)

        refresh = PushButton(FluentIcon.SYNC, 'Обновить список устройств', self)
        refresh.clicked.connect(self._fill_devices)
        root.addWidget(refresh)
        root.addStretch(1)

        round_corners(primary, 12)
        round_corners(secondary, 12)
        round_corners(master, 12)
        round_corners(theme, 12)
        round_corners(self.primaryCombo, 8)
        round_corners(self.secondaryCombo, 8)
        round_corners(self.themeCombo, 8)
        round_corners(refresh, 8)

        self.primaryCombo.currentIndexChanged.connect(self._emit_devices)
        self.secondaryCombo.currentIndexChanged.connect(self._emit_devices)
        self.masterSlider.valueChanged.connect(
            lambda v: self.masterChanged.emit(v / 100))
        self.themeCombo.currentIndexChanged.connect(
            lambda i: self.themeChanged.emit(('auto', 'light', 'dark')[i]))

        self._fill_devices()

    def _fill_devices(self):
        devs = self.engine.list_devices()
        for combo, ids, none_label, current in (
            (self.primaryCombo, self._p_ids, 'По умолчанию (система)',
             self.settings.primary),
            (self.secondaryCombo, self._s_ids, 'Не использовать',
             self.settings.secondary),
        ):
            combo.blockSignals(True)
            combo.clear()
            ids.clear()
            ids.append(None)
            combo.addItem(none_label)
            for i, name in devs:
                combo.addItem(name)
                ids.append(i)
            combo.setCurrentIndex(ids.index(current) if current in ids else 0)
            combo.blockSignals(False)

    def _emit_devices(self, *_):
        p = self._p_ids[self.primaryCombo.currentIndex()]
        s = self._s_ids[self.secondaryCombo.currentIndex()]
        self.devicesChanged.emit(p, s)


# ===================== welcome-экран =====================

class LogoWidget(QWidget):
    """Анимированный логотип: эквалайзер в круге."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(124, 124)
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        self._t += 0.10
        self.update()

    def stop(self):
        self._timer.stop()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        circle = QPainterPath()
        circle.addEllipse(QRectF(2, 2, w - 4, h - 4))

        g = QLinearGradient(QPointF(0, 0), QPointF(w, h))
        g.setColorAt(0.0, QColor('#4aa8ff'))
        g.setColorAt(1.0, ACCENT)
        p.setPen(Qt.NoPen)
        p.fillPath(circle, QBrush(g))
        p.setPen(QPen(QColor(255, 255, 255, 60), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(1, 1, w - 2, h - 2))

        n, bw, gap = 5, 9, 8
        total = n * bw + (n - 1) * gap
        x = (w - total) / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 240))
        for i in range(n):
            k = abs(math.sin(self._t + i * 1.25))
            bh = 16 + k * 46
            p.drawRoundedRect(QRectF(x, (h - bh) / 2, bw, bh), bw / 2, bw / 2)
            x += bw + gap
        p.end()


class HoldButton(QWidget):
    """Кнопка «удержи, чтобы войти»: заполняется, пока зажата."""
    completed = Signal()
    HOLD_MS = 900          # сколько держать для входа

    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(232, 58)
        self._text = text
        self._progress = 0.0
        self._anim = QPropertyAnimation(self, b'progress', self)
        self._anim.setEasingCurve(QEasingCurve.InOutSine)
        self._anim.finished.connect(self._on_finished)

    def _get_progress(self):
        return self._progress

    def _set_progress(self, value):
        self._progress = value
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def _run(self, ms, target):
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(target)
        self._anim.setDuration(max(1, int(ms)))
        self._anim.start()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._run(self.HOLD_MS * (1.0 - self._progress), 1.0)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and 0 < self._progress < 1.0:
            self._run(180 * self._progress, 0.0)      # плавный откат

    def leaveEvent(self, e):
        if 0 < self._progress < 1.0:
            self._run(160, 0.0)
        super().leaveEvent(e)

    def _on_finished(self):
        if self._progress >= 1.0:
            self.completed.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        dark = isDarkTheme()
        base = QColor(255, 255, 255, 28) if dark else QColor(0, 0, 0, 22)
        border = QColor(255, 255, 255, 70) if dark else QColor(0, 0, 0, 50)
        text_main = QColor(255, 255, 255, 225) if dark else QColor(20, 21, 26, 220)

        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), h / 2, h / 2)

        p.setPen(Qt.NoPen)
        p.fillPath(path, base)

        fill = int(self._progress * w)
        if fill > 0:
            g = QLinearGradient(QPointF(0, 0), QPointF(w, 0))
            g.setColorAt(0.0, ACCENT)
            g.setColorAt(1.0, QColor('#4aa8ff'))
            p.setClipPath(path)
            p.fillRect(QRect(0, 0, fill, h), QBrush(g))

        p.setPen(QPen(border, 1))
        p.setBrush(Qt.NoBrush)
        p.setClipRect(self.rect())
        p.drawPath(path)

        f = p.font()
        f.setPointSize(14)
        f.setBold(True)
        p.setFont(f)
        p.setPen(text_main)
        p.drawText(self.rect(), Qt.AlignCenter, self._text)
        if fill > 0:
            p.setClipRect(QRect(0, 0, fill, h))
            p.setPen(Qt.white)
            p.drawText(self.rect(), Qt.AlignCenter, self._text)
        p.end()


class WelcomeScreen(QWidget):
    """Стартовый экран «Welcome to Sounder»: вход по удержанию кнопки."""
    entered = Signal()
    _snapshot = None          # снимок экрана для затухания (без graphics effect)
    _alpha = 1.0
    _fade_anim = None

    def __init__(self, parent=None):
        super().__init__(parent)
        dark = isDarkTheme()
        text = '#ffffff' if dark else '#17181c'
        sub = 'rgba(255,255,255,160)' if dark else 'rgba(0,0,0,150)'
        foot = 'rgba(255,255,255,110)' if dark else 'rgba(0,0,0,105)'

        self.logo = LogoWidget(self)

        self.titleLabel = QLabel('Welcome to Sounder', self)
        self.titleLabel.setAlignment(Qt.AlignCenter)
        self.titleLabel.setStyleSheet(
            'background:transparent; color:%s; font-size:46px; font-weight:800;'
            % text)

        self.hintLabel = QLabel('Удерживайте кнопку, чтобы войти', self)
        self.hintLabel.setAlignment(Qt.AlignCenter)
        self.hintLabel.setStyleSheet(
            'background:transparent; color:%s; font-size:15px;' % sub)

        self.holdBtn = HoldButton('Lets sound!', self)
        self.holdBtn.completed.connect(self.entered.emit)

        footer = QLabel('Sounder 2.0', self)
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet('background:transparent; color:%s; font-size:12px;'
                             % foot)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 34)
        root.addStretch(4)
        root.addWidget(self.logo, 0, Qt.AlignHCenter)
        root.addSpacing(30)
        root.addWidget(self.titleLabel, 0, Qt.AlignHCenter)
        root.addSpacing(10)
        root.addWidget(self.hintLabel, 0, Qt.AlignHCenter)
        root.addSpacing(38)
        root.addWidget(self.holdBtn, 0, Qt.AlignHCenter)
        root.addStretch(5)
        root.addWidget(footer, 0, Qt.AlignHCenter)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        if self._snapshot is not None:          # режим затухания: только снимок
            p.setOpacity(self._alpha)
            p.drawPixmap(self.rect(), self._snapshot)
            p.end()
            return

        dark = isDarkTheme()
        p.fillRect(self.rect(), QColor('#191b20') if dark else QColor('#f5f6fa'))
        glow = QRadialGradient(self.logo.geometry().center(), 360)
        glow.setColorAt(0.0, QColor(0, 120, 212, 95 if dark else 70))
        glow.setColorAt(1.0, QColor(0, 120, 212, 0))
        p.fillRect(self.rect(), QBrush(glow))
        p.end()

    def fade_out(self):
        """Затухание без QGraphicsOpacityEffect. Делаем снимок экрана
        и рисуем его с убывающей альфой."""
        self.logo.stop()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._snapshot = self.grab()            # фиксируем текущий вид экрана
        for child in self.findChildren(QWidget):
            child.hide()                        # живые виджеты больше не нужны

        anim = QVariantAnimation(self)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setDuration(500)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.valueChanged.connect(self._set_alpha)
        anim.finished.connect(self._on_faded)
        anim.start()
        self._fade_anim = anim                  # держим ссылку до конца

    def _set_alpha(self, value):
        self._alpha = float(value)
        self.update()

    def _on_faded(self):
        self.setParent(None)
        self.deleteLater()


# ===================== главное окно =====================

class MainWindow(FluentWindow):
    _welcome = None          # атрибут класса: существует ещё до __init__,
                             # поэтому eventFilter не упадёт раньше времени

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Sounder')
        self.resize(1100, 720)
        self.setAcceptDrops(True)

        self.settings = Settings()
        self.settings.load()
        self.engine = AudioEngine(self)
        self.library = SoundLibrary()
        failed = self.library.load_all()
        self.hotkeys = HotkeyManager(self)

        self.board = SoundboardPage(self.engine, self.library, self.hotkeys, self)
        self.settingsPage = SettingsPage(self.engine, self.settings, self)

        self.addSubInterface(self.board, FluentIcon.ALBUM, 'Звуки')
        self.addSubInterface(self.settingsPage, FluentIcon.SETTING, 'Настройки',
                             NavigationItemPosition.BOTTOM)

        self.settingsPage.devicesChanged.connect(self._on_devices)
        self.settingsPage.masterChanged.connect(self._on_master)
        self.settingsPage.themeChanged.connect(self._on_theme)
        self.hotkeys.triggered.connect(self._on_hotkey)
        self.engine.deviceError.connect(
            lambda m: InfoBar.error('Аудио', m, parent=self,
                                    position=InfoBarPosition.TOP, duration=4000))

        # применяем сохранённые настройки
        self.engine.set_master(self.settings.master)
        self.engine.set_devices(self.settings.primary, self.settings.secondary)
        setTheme({'dark': Theme.DARK, 'light': Theme.LIGHT}.get(
            self.settings.theme, Theme.AUTO))
        QTimer.singleShot(0, reapply_rounding)   # тема перезаписала стили

        for s in self.library.sounds:
            if s.hotkey:
                self.hotkeys.bind(s.id, s.hotkey)

        if failed:
            InfoBar.warning('Библиотека',
                            f'Не удалось загрузить файлов: {len(failed)}',
                            parent=self, position=InfoBarPosition.TOP, duration=4000)

        if sys.platform == 'win32':
            try:
                self.setMicaEffectEnabled(True)   # эффект Mica на Windows 11
            except Exception:
                pass

        self._saveTimer = QTimer(self)
        self._saveTimer.setSingleShot(True)
        self._saveTimer.setInterval(400)
        self._saveTimer.timeout.connect(self.settings.save)

        # welcome-экран: вход по удержанию кнопки
        self._welcome = WelcomeScreen(self)
        self._welcome.entered.connect(self._on_welcome_entered)
        self._welcome.setGeometry(self.rect())
        self._welcome.raise_()
        self.hotkeys.suspend()          # хоткеи включатся после входа
        self.installEventFilter(self)

    def eventFilter(self, obj, e):
        # welcome-экран всегда на весь экран, даже при ресайзе.
        # getattr — страховка: метод может быть вызван базовым классом
        # ещё до завершения __init__.
        if obj is self and getattr(self, '_welcome', None) is not None:
            if e.type() in (QEvent.Show, QEvent.Resize):
                self._welcome.setGeometry(self.rect())
                self._welcome.raise_()
        return super().eventFilter(obj, e)

    def _on_welcome_entered(self):
        welcome, self._welcome = self._welcome, None
        if welcome is not None:
            welcome.fade_out()
        self.hotkeys.resume()

    def _on_devices(self, primary, secondary):
        self.settings.primary = primary
        self.settings.secondary = secondary
        self.settings.save()
        self.engine.set_devices(primary, secondary)

    def _on_master(self, value):
        self.settings.master = value
        self.engine.set_master(value)
        self._saveTimer.start()          # сохраняем с задержкой — не спамим диск

    def _on_theme(self, name):
        self.settings.theme = name
        self.settings.save()
        setTheme({'dark': Theme.DARK, 'light': Theme.LIGHT}.get(name, Theme.AUTO))
        QTimer.singleShot(0, reapply_rounding)

    def _on_hotkey(self, sound_id):
        sound = self.library.get(sound_id)
        if sound:
            self.engine.play(sound)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dropEvent(self, e):
        added = 0
        for url in e.mimeData().urls():
            if url.isLocalFile() and \
                    self.board.add_sound_interactive(url.toLocalFile()):
                added += 1
        if added:
            InfoBar.success('Добавлено', f'Новых звуков: {added}',
                            parent=self, position=InfoBarPosition.TOP)
        e.acceptProposedAction()

    def closeEvent(self, e):
        self.engine.close()
        self.hotkeys.shutdown()
        self.library.save()
        self.settings.save()
        super().closeEvent(e)