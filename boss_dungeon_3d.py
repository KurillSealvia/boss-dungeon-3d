# -*- coding: utf-8 -*-
"""Подземелье боссов 3D — роглайк-арена на Ursina.

Управление:
    WASD      — движение
    Мышь      — обзор (в видах от 1-го и 3-го лица)
    ЛКМ       — выстрел
    Space     — рывок (неуязвимость)
    Q         — взрыв вокруг себя
    E         — щит
    V         — сменить вид: 3-е лицо / 1-е лицо / сверху
    Esc       — меню / пауза
    1/2/3     — выбор реликвии
    Enter     — новый забег после смерти

Запуск:  python boss_dungeon_3d.py
"""
import sys
import math
import random
import json
import os

from ursina import *

TEST = '--test' in sys.argv

app = Ursina(title='Подземелье боссов 3D', borderless=False, fullscreen=False, vsync=True,
             editor_ui_enabled=False)
window.color = color.rgb32(7, 9, 16)

# ------------------------------------------------------------------ настройки
GAME_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(GAME_DIR, 'settings.json')
DEFAULT_SETTINGS = {'sens': 110.0, 'fov': 62.0, 'view': 'third'}
SETTINGS = dict(DEFAULT_SETTINGS)

UI_STATE = 'menu'       # menu | settings | game | paused
UI_BACK = 'menu'        # куда возвращаться из настроек


def load_settings():
    """Читает settings.json; при ошибке остаются значения по умолчанию."""
    try:
        with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception:
        return
    if not isinstance(raw, dict):
        return
    v = raw.get('sens')
    if isinstance(v, (int, float)):
        SETTINGS['sens'] = max(40.0, min(300.0, float(v)))
    v = raw.get('fov')
    if isinstance(v, (int, float)):
        SETTINGS['fov'] = max(50.0, min(100.0, float(v)))
    v = raw.get('view')
    if v in ('third', 'first', 'top'):
        SETTINGS['view'] = v


def save_settings():
    if TEST:
        return
    try:
        with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(SETTINGS, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


load_settings()

HALF = 10.0          # половина арены
FLOORS = 5

# ------------------------------------------------------------------ сцена
ground = Entity(
    model='plane', scale=HALF * 2, texture='white_cube', texture_scale=(HALF * 2, HALF * 2),
    color=color.rgb32(24, 29, 44), collider='box',
)
for i in range(4):
    ang = i * 90
    w = Entity(model='cube', color=color.rgb32(18, 21, 34), scale=(HALF * 2 + 1, 1.2, 0.6),
               position=(0, 0.6, -HALF) if i == 0 else (0, 0.6, HALF) if i == 2 else (-HALF, 0.6, 0) if i == 3 else (HALF, 0.6, 0),
               rotation_y=ang)

# декоративные огни по углам
for sx in (-1, 1):
    for sz in (-1, 1):
        Entity(model='cube', scale=0.25, position=(sx * (HALF - 0.6), 0.25, sz * (HALF - 0.6)), color=color.cyan)

# ------------------------------------------------------------------ игрок
player = Entity(model='sphere', color=color.azure, scale=0.85, position=(0, 0.9, 7))
player_ring = Entity(model='circle', rotation_x=90, scale=1.4, color=color.rgba32(77, 225, 255, 70),
                     position=(0, 0.03, 7), unlit=True)

P = {
    'hp': 100, 'max_hp': 100,
    'speed': 7.0,
    'dmg': 14,
    'fire_cd': 0.0, 'fire_rate': 0.26,
    'dash_cd': 0.0, 'dash_cd_max': 3.0, 'iframe': 0.0,
    'shield_t': 0.0, 'shield_mult': 0.4,
    'blast_cd': 0.0, 'blast_cd_max': 8.0, 'blast_dmg': 45,
    'lifesteal': 0.0, 'crit': 0.0,
    'dmg_mult': 1.0,
}

ST = {'floor': 0, 'phase': 'fight', 'order': [], 'bosses': [], 'relics': [],
      'pending': [], 'projectiles': [], 'telegraphs': [], 'style': 'ranger'}

# ------------------------------------------------------------------ стили боя
STYLES = {
    'ranger': {
        'name': 'Стрелок',
        'line': 'Точный одиночный выстрел',
        'stats': '14 урона · 0.26 с',
        'note': 'любая дистанция',
        'color': color.rgb32(255, 206, 120),
    },
    'storm': {
        'name': 'Шквал',
        'line': 'Очередь из трёх снарядов',
        'stats': '9×3 урона · 0.55 с',
        'note': 'рывок быстрее',
        'color': color.rgb32(120, 220, 255),
    },
    'shotgun': {
        'name': 'Дробовик',
        'line': 'Веер из шести дробин',
        'stats': '8×6 урона · 0.85 с',
        'note': '+20 здоровья',
        'color': color.rgb32(255, 140, 110),
    },
    'blade': {
        'name': 'Клинок',
        'line': 'Круговой удар вокруг себя',
        'stats': '30 урона · 0.42 с',
        'note': 'скорость +15%',
        'color': color.rgb32(120, 240, 190),
    },
}
STYLE_ORDER = ('ranger', 'storm', 'shotgun', 'blade')

# ------------------------------------------------------------------ камера
cam_target = Entity(position=player.position)
camera.position = cam_target.position + Vec3(0, 15.5, 13)
camera.rotation = (50, 180, 0)
camera.fov = SETTINGS['fov']

CAM_MODES = ('third', 'first', 'top')
MODE_NAMES = {'third': '3-е лицо', 'first': '1-е лицо', 'top': 'сверху'}
CAM_MODE = SETTINGS['view']  # вид из настроек
YAW = 180.0                 # поворот камеры по горизонтали
PITCH = 30.0                # наклон (положительный = смотрим вниз)
MOUSE_SENS = SETTINGS['sens']
THIRD_DIST = 6.5
THIRD_LIFT = 6.0            # прицел чуть выше игрока в режиме от 3-го лица
PLAYER_EYE = 0.35
PITCH_MEM = {'third': 30.0, 'first': 0.0}
MENU_ANGLE = 25.0

CAM_FWD = Vec3(0, 0, -1)
CAM_RIGHT = Vec3(-1, 0, 0)
_lock_state = None


def apply_settings():
    """Применяет сохранённые настройки к движку."""
    global MOUSE_SENS
    MOUSE_SENS = SETTINGS['sens']
    camera.fov = SETTINGS['fov']


def lock_mouse(force=False):
    """Курсор захвачен только в бою и только в видах от 1-го/3-го лица."""
    global _lock_state
    need = (UI_STATE == 'game' and CAM_MODE != 'top' and ST.get('phase') == 'fight')
    if need != _lock_state or force:
        _lock_state = need
        try:
            mouse.locked = need
        except Exception:
            pass


def set_mode(mode):
    global CAM_MODE, PITCH
    if CAM_MODE in PITCH_MEM:
        PITCH_MEM[CAM_MODE] = PITCH
    CAM_MODE = mode
    if mode in PITCH_MEM:
        PITCH = PITCH_MEM[mode]
    first = (mode == 'first')
    player.enabled = not first
    player_ring.enabled = not first
    lock_mouse()


def cycle_mode():
    mode = CAM_MODES[(CAM_MODES.index(CAM_MODE) + 1) % len(CAM_MODES)]
    set_mode(mode)
    SETTINGS['view'] = mode
    save_settings()
    refresh_view_buttons()

# ------------------------------------------------------------------ UI
ui_hp_bg = Entity(parent=camera.ui, model='quad', scale=(0.44, 0.024), position=(-0.52, 0.44),
                  origin=(-0.5, 0), color=color.rgba32(255, 255, 255, 25))
ui_hp = Entity(parent=ui_hp_bg, model='quad', scale=(1, 1), origin=(-0.5, 0), position=(-0.5, 0), z=-0.01,
               color=color.rgb32(255, 72, 104))
ui_hp_txt = Text(parent=camera.ui, text='', position=(-0.52, 0.465), origin=(-0.5, 0), scale=0.9)

ui_boss_bg = Entity(parent=camera.ui, model='quad', scale=(0.56, 0.018), position=(0, 0.43),
                    origin=(0, 0), color=color.rgba32(255, 255, 255, 22))
ui_boss = Entity(parent=ui_boss_bg, model='quad', scale=(1, 1), origin=(-0.5, 0), position=(-0.5, 0), z=-0.01,
                 color=color.rgb32(255, 150, 80))
ui_boss_txt = Text(parent=camera.ui, text='', position=(0, 0.45), origin=(0, 0), scale=0.85,
                   color=color.rgb32(255, 210, 160))

ui_floor = Text(parent=camera.ui, text='', position=(0.86, 0.47), origin=(0.5, 0), scale=0.9,
                color=color.rgb32(150, 160, 200))
# ------------------------------------------------------------------ иконки способностей
ABILITY_COLORS = {
    'fire': color.rgb32(255, 206, 120),
    'dash': color.rgb32(120, 220, 255),
    'blast': color.rgb32(255, 140, 110),
    'shield': color.rgb32(120, 240, 190),
}
ABILITY_ICONS = {}
ability_bar = Entity(parent=camera.ui)


def _icon_shape(slot, model, scale, pos, rot, col):
    return Entity(parent=slot, model=model, scale=scale, position=pos,
                  rotation_z=rot, color=col, z=-1)


def _make_ability(kind, idx, key):
    col = ABILITY_COLORS[kind]
    c0, c1, c2 = col[0], col[1], col[2]
    dim = color.rgba(c0, c1, c2, 0.55)
    slot = Entity(parent=ability_bar, position=(-0.80 + idx * 0.10, -0.435))

    # глоу-ореол (за иконкой): виден только когда способность готова
    glow = Entity(parent=slot, z=2, enabled=False)
    halo_out = Entity(parent=glow, model='circle', scale=0.122,
                      color=color.rgba(c0, c1, c2, 0.13))
    halo_in = Entity(parent=glow, model='circle', scale=0.101,
                     color=color.rgba(c0, c1, c2, 0.22))

    # рамка + тёмная подложка
    frame = Entity(parent=slot, model=Quad(radius=0.20), scale=(0.094, 0.094), z=1,
                   color=color.rgba(c0, c1, c2, 0.42))
    Entity(parent=slot, model=Quad(radius=0.20), scale=(0.086, 0.086), z=0,
           color=color.rgba32(12, 16, 26, 245))

    if kind == 'fire':          # снаряд с хвостом
        _icon_shape(slot, 'quad', (0.030, 0.010), (-0.013, 0.002), -18, dim)
        _icon_shape(slot, 'circle', 0.024, (0.011, 0.002), 0, col)
    elif kind == 'dash':        # стрелка
        _icon_shape(slot, 'quad', (0.034, 0.010), (-0.007, 0), 0, col)
        _icon_shape(slot, 'quad', (0.020, 0.020), (0.019, 0), 45, col)
    elif kind == 'blast':       # центр + лучи
        _icon_shape(slot, 'circle', 0.020, (0, 0), 0, col)
        _icon_shape(slot, 'quad', (0.013, 0.006), (0.027, 0), 0, dim)
        _icon_shape(slot, 'quad', (0.013, 0.006), (-0.027, 0), 0, dim)
        _icon_shape(slot, 'quad', (0.013, 0.006), (0, 0.027), 90, dim)
        _icon_shape(slot, 'quad', (0.013, 0.006), (0, -0.027), 90, dim)
    elif kind == 'shield':      # ромб-контур
        _icon_shape(slot, 'quad', (0.036, 0.036), (0, 0.002), 45, col)
        _icon_shape(slot, 'quad', (0.023, 0.023), (0, 0.002), 45, color.rgba32(12, 16, 26, 255))

    # затемнение при перезарядке (растёт сверху вниз)
    overlay = Entity(parent=slot, model=Quad(radius=0.16), origin_y=0.5,
                     position=(0, 0.042), scale=(0.084, 0.001), z=-2,
                     color=color.rgba32(0, 0, 0, 205), enabled=False)
    txt = Text(parent=slot, text='', position=(0, 0), origin=(0, 0), scale=0.9,
               color=color.rgb32(240, 244, 255), z=-3)
    Text(parent=slot, text=key, position=(0, 0.058), origin=(0, 0), scale=0.55,
         color=color.rgb32(140, 152, 192))

    ABILITY_ICONS[kind] = {'overlay': overlay, 'text': txt, 'glow': glow,
                           'halo_out': halo_out, 'halo_in': halo_in, 'frame': frame,
                           'rgb': (c0, c1, c2), 'ready': False, 'pulse': 0.0,
                           'phase': idx * 1.7}


for _i, (_kind, _key) in enumerate((('fire', 'ЛКМ'), ('dash', 'SPACE'),
                                    ('blast', 'Q'), ('shield', 'E'))):
    _make_ability(_kind, _i, _key)
ui_msg = Text(parent=camera.ui, text='', position=(0, 0.30), origin=(0, 0), scale=1.05)
ui_center = Text(parent=camera.ui, text='', position=(0, 0.05), origin=(0, 0), scale=1.6)
ui_center_bg = Entity(parent=camera.ui, model='quad', scale=(2.6, 1.5), z=1,
                      color=color.rgba32(3, 5, 12, 190), enabled=False)
ui_relics = Text(parent=camera.ui, text='', position=(0.86, 0.40), origin=(0.5, 0), scale=0.9,
                 color=color.rgb32(255, 210, 150))
ui_mode = Text(parent=camera.ui, text='', position=(-0.86, 0.40), origin=(-0.5, 0), scale=0.8,
               color=color.rgb32(120, 132, 175))
ui_style = Text(parent=camera.ui, text='', position=(-0.86, 0.365), origin=(-0.5, 0), scale=0.8,
                color=color.rgb32(255, 205, 140))

cross_h = Entity(parent=camera.ui, model='quad', scale=(0.015, 0.0016),
                 color=color.rgba32(255, 255, 255, 205), z=-1, enabled=False)
cross_v = Entity(parent=camera.ui, model='quad', scale=(0.0016, 0.015),
                 color=color.rgba32(255, 255, 255, 205), z=-1, enabled=False)

HUD_ENTITIES = [ui_hp_bg, ui_hp_txt, ui_boss_bg, ui_boss_txt, ui_floor,
                ability_bar, ui_msg, ui_relics, ui_mode, ui_style, cross_h, cross_v]


def set_hud_visible(flag):
    for e in HUD_ENTITIES:
        try:
            e.enabled = flag
        except Exception:
            pass

msg_timer = 0.0


def say(text, duration=2.0, col=color.white):
    global msg_timer
    ui_msg.text = text
    ui_msg.color = col
    msg_timer = duration


# ------------------------------------------------------------------ реликвии
RELICS = {
    'hp':     ('HP', 'Стальное сердце', '+25 HP и лечение'),
    'dmg':    ('DMG', 'Точный удар', 'урон +25%'),
    'speed':  ('SPD', 'Быстрые ноги', 'скорость +20%'),
    'dash':   ('DASH', 'Импульс', 'рывок быстрее на 1 с'),
    'shield': ('SHD', 'Тяжёлый щит', 'щит держится на 2 с дольше'),
    'blast':  ('AOE', 'Осколки', 'взрыв +25 урона'),
    'life':   ('LIFE', 'Вампиризм', '+1.5 HP за попадание'),
    'crit':   ('CRIT', 'Клинок закалён', '25% шанс двойного урона'),
    'rate':   ('RATE', 'Скорострельность', 'темп стрельбы +25%'),
}


def apply_relic(rid):
    ST['relics'].append(rid)
    if rid == 'hp':
        P['max_hp'] += 25
        P['hp'] = min(P['max_hp'], P['hp'] + 25)
    elif rid == 'dmg':
        P['dmg_mult'] *= 1.25
    elif rid == 'speed':
        P['speed'] *= 1.2
    elif rid == 'dash':
        P['dash_cd_max'] = max(1.2, P['dash_cd_max'] - 1.0)
    elif rid == 'shield':
        P['shield_max'] += 2.0
    elif rid == 'blast':
        P['blast_dmg'] += 25
    elif rid == 'life':
        P['lifesteal'] += 1.5
    elif rid == 'crit':
        P['crit'] += 0.25
    elif rid == 'rate':
        P['fire_rate'] = max(0.10, P['fire_rate'] / 1.25)
    say('Реликвия: ' + RELICS[rid][1], 2.2, color.rgb32(255, 210, 120))
# ------------------------------------------------------------------ утилиты боя
def dist2(a, b):
    return math.hypot(a.x - b.x, a.z - b.z)


def flat(v):
    return Vec3(v.x, 0, v.z)


def rotate_dir(d, deg):
    """Поворот плоского направления вокруг вертикали (для разброса)."""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return Vec3(d.x * c - d.z * s, 0, d.x * s + d.z * c)


def clamp_arena(v, margin=0.8):
    v.x = max(-HALF + margin, min(HALF - margin, v.x))
    v.z = max(-HALF + margin, min(HALF - margin, v.z))
    return v


def seg_dist(p, a, b):
    ab = Vec3(b.x - a.x, 0, b.z - a.z)
    ap = Vec3(p.x - a.x, 0, p.z - a.z)
    L = ab.length()
    if L < 0.0001:
        return Vec3(ap.x, 0, ap.z).length()
    t = max(0.0, min(1.0, (ap.x * ab.x + ap.z * ab.z) / (L * L)))
    c = Vec3(a.x + ab.x * t, 0, a.z + ab.z * t)
    return Vec3(p.x - c.x, 0, p.z - c.z).length()


# ------------------------------------------------------------------ телеграфы
class Zone(Entity):
    """Круговая или линейная зона поражения с предупреждением."""

    def __init__(self, pos, radius=3.0, delay=1.0, dmg=15, shape='circle', end=None, width=2.0, follow=None):
        self.shape = shape
        self.radius = radius
        self.width = width
        self.dmg = dmg
        self.delay = max(0.15, delay)
        self.timer = self.delay
        self.done = False
        self.end = Vec3(end) if end is not None else None
        self.pos0 = Vec3(pos)

        if shape == 'circle':
            super().__init__(model='circle', rotation_x=90, position=self.pos0 + Vec3(0, 0.05, 0),
                             scale=radius * 2, color=color.rgba32(255, 60, 80, 55), unlit=True, double_sided=True)
            self.inner = Entity(model='circle', rotation_x=90, position=self.pos0 + Vec3(0, 0.06, 0),
                                scale=0.01, color=color.rgba32(255, 90, 110, 150), unlit=True, double_sided=True)
        else:
            d = Vec3(self.end.x - self.pos0.x, 0, self.end.z - self.pos0.z)
            self.length = max(0.5, d.length())
            mid = self.pos0 + d / 2
            self.angle = math.degrees(math.atan2(d.x, d.z))
            super().__init__(model='cube', position=mid + Vec3(0, 0.05, 0),
                             scale=(width, 0.06, self.length), rotation_y=self.angle,
                             color=color.rgba32(255, 60, 80, 55), unlit=True)
            self.inner = Entity(model='cube', position=mid + Vec3(0, 0.065, 0), scale=(width * 0.3, 0.06, 0.01),
                                rotation_y=self.angle, color=color.rgba32(255, 90, 110, 150), unlit=True)

        ST['telegraphs'].append(self)

    def update(self):
        if self.done or UI_STATE != 'game':
            return
        self.timer -= time.dt
        k = max(0.02, 1.0 - max(0.0, self.timer) / self.delay)
        if self.shape == 'circle':
            self.inner.scale = (self.radius * 2 * k, self.radius * 2 * k)
        else:
            self.inner.scale = (self.width * k, 0.06, max(0.01, self.length * k))
        if self.timer <= 0:
            self.explode()

    def explode(self):
        self.done = True
        if self.shape == 'circle':
            hit = dist2(player.position, self.pos0) <= self.radius + 0.3
        else:
            hit = seg_dist(player.position, self.pos0, self.end) <= self.width / 2 + 0.3
        if hit:
            hurt_player(self.dmg)
        if self.inner:
            destroy(self.inner)
        destroy(self)


# ------------------------------------------------------------------ снаряды
class Bolt(Entity):
    def __init__(self, pos, direction, dmg, friendly=True, speed=26.0, life=1.6, col=None, size=None):
        if col is None:
            col = color.cyan if friendly else color.rgb32(200, 80, 255)
        if size is None:
            size = 0.34 if friendly else 0.5
        super().__init__(model='sphere', scale=size, position=pos, color=col, unlit=True)
        self.dir = direction.normalized()
        self.speed = speed
        self.dmg = dmg
        self.life = life
        self.friendly = friendly

    def update(self):
        if UI_STATE != 'game':
            return
        self.position += self.dir * self.speed * time.dt
        self.life -= time.dt
        if self.friendly:
            for b in ST['bosses']:
                if b['alive'] and dist2(self.position, b['ent'].position) < b['radius'] + 0.35:
                    damage_boss(b, self.dmg)
                    destroy(self)
                    return
        else:
            if dist2(self.position, player.position) < 0.75:
                hurt_player(self.dmg)
                destroy(self)
                return
        if self.life <= 0 or abs(self.position.x) > HALF or abs(self.position.z) > HALF:
            destroy(self)


# ------------------------------------------------------------------ урон
shake = 0.0


def hurt_player(n):
    if P['iframe'] > 0:
        return
    if P['shield_t'] > 0:
        n *= P['shield_mult']
        flash_shield()
    P['hp'] -= n
    global shake
    shake = min(0.45, shake + 0.18)
    player.color = color.rgb32(255, 120, 120)
    invoke(setattr, player, 'color', color.azure, delay=0.12)
    if P['hp'] <= 0:
        P['hp'] = 0
        die()


def damage_boss(b, n):
    if not b['alive']:
        return
    b['hp'] -= n
    if P['lifesteal'] > 0:
        P['hp'] = min(P['max_hp'], P['hp'] + P['lifesteal'])
    b['ent'].color = color.white
    invoke(safe_color, b['ent'], b['base_color'], delay=0.08)
    b['flash'] = 0.12
    if b['hp'] <= 0:
        kill_boss(b)


def safe_color(ent, col):
    """Отложенная смена цвета, безопасная для уже уничтоженных сущностей."""
    try:
        if not ent.is_empty():
            ent.color = col
    except Exception:
        pass


def safe_scale(ent, s):
    """Отложенная смена масштаба, безопасная для уже уничтоженных сущностей."""
    try:
        if not ent.is_empty():
            ent.scale = s
    except Exception:
        pass


def flash_shield():
    player_ring.color = color.rgba32(120, 220, 255, 200)
    invoke(setattr, player_ring, 'color', color.rgba32(77, 225, 255, 70), delay=0.15)


def shake_cam(amount=0.25):
    global shake
    shake = min(0.5, shake + amount)


# ------------------------------------------------------------------ действия игрока
def move_dir():
    v = Vec3(0, 0, 0)
    if CAM_MODE == 'top':
        if held_keys['w']:
            v += Vec3(0, 0, -1)
        if held_keys['s']:
            v += Vec3(0, 0, 1)
        if held_keys['a']:
            v += Vec3(1, 0, 0)
        if held_keys['d']:
            v += Vec3(-1, 0, 0)
    else:
        v = CAM_FWD * (held_keys['w'] - held_keys['s']) + CAM_RIGHT * (held_keys['d'] - held_keys['a'])
    return v.normalized() if v.length() > 0 else v


def aim_point():
    if CAM_MODE != 'top':
        return player.position + CAM_FWD * 12
    try:
        wp = mouse.world_point
    except Exception:
        wp = None
    if wp is not None:
        return Vec3(wp.x, 0, wp.z)
    return player.position + Vec3(0, 0, -5)


def _fire_bolt(direction, dmg, life=1.6, speed=26.0):
    d = flat(direction)
    if d.length() < 0.001:
        d = Vec3(0, 0, -1)
    d = d.normalized()
    Bolt(player.position + Vec3(0, 0.15, 0) + d * 0.7, d, dmg, speed=speed, life=life)


def _burst_shot(direction, dmg):
    if UI_STATE != 'game' or ST['phase'] != 'fight':
        return
    _fire_bolt(direction, dmg)


def shoot():
    """Атака ЛКМ — зависит от выбранного стиля боя."""
    if P['fire_cd'] > 0:
        return

    sid = ST.get('style', 'ranger')
    base = flat(aim_point() - player.position)
    if base.length() < 0.2:
        base = Vec3(0, 0, -1)
    base = base.normalized()

    mult = P['dmg_mult']
    crit = P['crit'] > 0 and random.random() < P['crit']
    rate_k = max(0.5, P['fire_rate'] / 0.26)

    if sid == 'storm':
        P['fire_cd'] = P['fire_cd_max'] = 0.55 * rate_k
        dmg = round(9 * mult * (2 if crit else 1))
        for i, ang in enumerate((-5.0, 0.0, 5.0)):
            invoke(_burst_shot, rotate_dir(base, ang), dmg, delay=i * 0.06)
        return

    if sid == 'shotgun':
        P['fire_cd'] = P['fire_cd_max'] = 0.85 * rate_k
        dmg = round(8 * mult * (2 if crit else 1))
        for ang in (-18, -11, -4, 3, 10, 17):
            _fire_bolt(rotate_dir(base, ang), dmg, life=0.32, speed=30)
        return

    if sid == 'blade':
        P['fire_cd'] = P['fire_cd_max'] = 0.42 * rate_k
        dmg = round(30 * mult * (2 if crit else 1))
        Ring(player.position, 0, 2.6, col=STYLES['blade']['color'])
        for b in ST['bosses']:
            if b['alive'] and dist2(player.position, b['ent'].position) <= 2.6 + b['radius']:
                damage_boss(b, dmg)
        shake_cam(0.07)
        return

    # «Стрелок» — базовый одиночный выстрел
    P['fire_cd'] = P['fire_cd_max'] = P['fire_rate']
    dmg = round(14 * mult * (2 if crit else 1))
    _fire_bolt(base, dmg)


def dash():
    if P['dash_cd'] > 0:
        return
    d = move_dir()
    if d.length() == 0:
        d = Vec3(0, 0, -1)
    P['dash_cd'] = P['dash_cd_max']
    P['iframe'] = 0.45
    player.position = clamp_arena(player.position + d * 3.2)
    player_ring.color = color.rgba32(160, 250, 255, 210)
    invoke(setattr, player_ring, 'color', color.rgba32(77, 225, 255, 70), delay=0.25)


def blast():
    if P['blast_cd'] > 0:
        return
    P['blast_cd'] = P['blast_cd_max']
    Ring(player.position, P['blast_dmg'], 4.6)
    for b in ST['bosses']:
        if b['alive'] and dist2(player.position, b['ent'].position) <= 4.6 + b['radius']:
            damage_boss(b, P['blast_dmg'])
    shake_cam(0.2)


def use_shield():
    if P['shield_cd'] > 0:
        return
    P['shield_cd'] = P['shield_cd_max']
    P['shield_t'] = P['shield_max']
    say('Щит активен', 1.2, color.rgb32(120, 220, 255))


class Ring(Entity):
    """Визуальный расходящийся круг (взрыв или удар клинка)."""

    def __init__(self, pos, dmg, radius, col=None):
        if col is None:
            col = color.rgb32(120, 240, 255)
        self.base_col = (col[0], col[1], col[2])
        super().__init__(model='circle', rotation_x=90, position=Vec3(pos.x, 0.08, pos.z),
                         scale=0.5, color=color.rgba(col[0], col[1], col[2], 0.66),
                         unlit=True, double_sided=True)
        self.t = 0.0
        self.radius = radius

    def update(self):
        if UI_STATE != 'game':
            return
        self.t += time.dt
        k = min(1.0, self.t / 0.35)
        self.scale = (self.radius * 2 * k, self.radius * 2 * k)
        r, g, b = self.base_col
        self.color = color.rgba(r, g, b, 0.66 * (1 - k))
        if k >= 1.0:
            destroy(self)


# ------------------------------------------------------------------ ввод
def input(key):
    if key == 'escape':
        if UI_STATE == 'game':
            if ST['phase'] in ('dead', 'win'):
                quit_to_menu()
            else:
                pause_game()
        elif UI_STATE == 'paused':
            resume_game()
        elif UI_STATE == 'settings':
            close_settings()
        elif UI_STATE == 'style':
            show_main_menu()
        return
    if UI_STATE == 'menu':
        if key == 'enter':
            open_style_select()
        return
    if UI_STATE == 'style':
        if key in ('1', '2', '3', '4'):
            start_game(STYLE_ORDER[int(key) - 1])
        elif key == 'enter':
            start_game()
        return
    if UI_STATE != 'game':
        return
    if ST['phase'] == 'reward':
        if key in ('1', '2', '3'):
            pick_reward(int(key) - 1)
        return
    if ST['phase'] in ('dead', 'win'):
        if key == 'enter':
            open_style_select()
        return
    if ST['phase'] != 'fight':
        return
    if key == 'v':
        cycle_mode()
    elif key == 'left mouse down':
        shoot()
    elif key == 'space':
        dash()
    elif key == 'q':
        blast()
    elif key == 'e':
        use_shield()
# ------------------------------------------------------------------ боссы
BOSS_NAMES = {
    'twins': 'Близнецы-стражи',
    'trickster': 'Костяной шутник',
    'dancer': 'Клинок-вихрь',
    'king': 'Король пепла',
    'abyss': 'Рыцарь Бездны',
}
BOSS_KINDS = list(BOSS_NAMES)

# Ближний бой: (урон, запас дистанции сверх радиуса, кулдаун).
# Дальний бой: (тип, урон, кулдаун).
BOSS_AI = {
    'hammer':    {'melee': (16, 1.5, 2.6), 'ranged': None},
    'spear':     {'melee': (12, 1.4, 2.0), 'ranged': None},
    'trickster': {'melee': (11, 1.6, 2.4), 'ranged': ('volley', 9, 3.8)},
    'dancer':    {'melee': (13, 1.5, 1.8), 'ranged': None},
    'king':      {'melee': (15, 1.6, 2.4), 'ranged': ('fire', 13, 4.2)},
    'abyss':     {'melee': (17, 1.5, 2.2), 'ranged': ('bolt', 11, 3.4)},
}


def new_boss(name, kind, pos, hp, col, ring_col, scale=1.5, radius=1.0, speed=0.0, interval=3.0, dmg=15):
    e = Entity(model='sphere', color=col, position=pos, scale=scale)
    ring = Entity(model='circle', rotation_x=90, position=Vec3(pos.x, 0.04, pos.z),
                  scale=radius * 2.6, color=ring_col, unlit=True)
    ai = BOSS_AI.get(kind, {})
    melee = ai.get('melee')
    ranged = ai.get('ranged')
    return {
        'name': name, 'kind': kind, 'ent': e, 'ring': ring, 'base_color': col,
        'hp': hp, 'max_hp': hp, 'alive': True, 'radius': radius,
        'speed': speed, 'interval': interval, 'atk_timer': 1.6 + random.random(),
        'dmg': dmg, 'n': 0, 'enraged': False, 'flash': 0.0,
        'seed': random.random() * 6.28, 'home_y': pos.y,
        # ближняя атака
        'melee_dmg': melee[0] if melee else 0,
        'melee_range': radius + melee[1] if melee else 0.0,
        'melee_cd_max': melee[2] if melee else 0.0,
        'melee_cd': 1.2 if melee else 999.0,
        # дальняя атака
        'ranged_kind': ranged[0] if ranged else None,
        'ranged_dmg': ranged[1] if ranged else 0,
        'ranged_cd_max': ranged[2] if ranged else 0.0,
        'ranged_cd': 1.8 if ranged else 999.0,
        'pause': 0.0, 'taught': False,
    }


def make_bosses(kind, floor):
    k = 1.0 + 0.12 * (floor - 1)
    if kind == 'twins':
        return [
            new_boss('Страж-молот', 'hammer', Vec3(-3.5, 1.2, -4), int(240 * k), color.rgb32(255, 170, 90),
                     color.rgba32(255, 170, 90, 45), scale=1.9, radius=1.2, speed=1.3, interval=3.3, dmg=18),
            new_boss('Страж-копьё', 'spear', Vec3(3.5, 1.1, -4), int(210 * k), color.rgb32(255, 110, 130),
                     color.rgba32(255, 110, 130, 45), scale=1.4, radius=0.9, speed=2.6, interval=2.7, dmg=15),
        ]
    if kind == 'trickster':
        return [new_boss('Костяной шутник', 'trickster', Vec3(0, 1.2, -4), int(280 * k), color.rgb32(220, 230, 255),
                         color.rgba32(200, 210, 255, 45), scale=1.5, radius=0.9, speed=0.0, interval=2.6, dmg=16)]
    if kind == 'dancer':
        return [new_boss('Клинок-вихрь', 'dancer', Vec3(0, 1.1, -4), int(340 * k), color.rgb32(180, 90, 255),
                         color.rgba32(180, 90, 255, 45), scale=1.5, radius=1.0, speed=3.0, interval=3.0, dmg=15)]
    if kind == 'king':
        return [new_boss('Король пепла', 'king', Vec3(0, 1.3, -4), int(400 * k), color.rgb32(255, 140, 60),
                         color.rgba32(255, 140, 60, 45), scale=1.9, radius=1.2, speed=1.8, interval=2.6, dmg=15)]
    return [new_boss('Рыцарь Бездны', 'abyss', Vec3(0, 1.2, -4), int(370 * k), color.rgb32(140, 120, 255),
                     color.rgba32(140, 120, 255, 45), scale=1.7, radius=1.1, speed=2.2, interval=3.1, dmg=19)]


def update_boss(b, dt):
    if not b['alive']:
        return
    e = b['ent']
    e.y = b['home_y'] + math.sin(time.time() * 2 + b['seed']) * 0.16
    b['ring'].position = Vec3(e.position.x, 0.04, e.position.z)

    b['pause'] = max(0.0, b['pause'] - dt)
    if b['speed'] > 0 and b['pause'] <= 0:
        d = flat(player.position - e.position)
        if d.length() > 2.1:
            e.position += d.normalized() * b['speed'] * dt
            clamp_arena(e.position)
        b['ring'].position = Vec3(e.position.x, 0.04, e.position.z)

    if ST['phase'] != 'fight':
        return

    b['melee_cd'] -= dt
    b['ranged_cd'] -= dt
    dist = dist2(player.position, e.position)
    enr = 0.7 if b['enraged'] else 1.0

    # ближний удар: наказывает за то, что игрок стоит вплотную
    if b['melee_cd'] <= 0 and dist <= b['melee_range']:
        boss_melee(b)
        b['melee_cd'] = b['melee_cd_max'] * enr

    # дальняя атака: заставляет двигаться, а не только уворачиваться от зон
    if b['ranged_kind']:
        if b['ranged_cd'] <= 0:
            if dist > 4.2:
                boss_ranged(b)
                b['ranged_cd'] = b['ranged_cd_max'] * enr
            else:
                b['ranged_cd'] = 0.8      # слишком близко — попробует позже

    b['atk_timer'] -= dt
    if b['atk_timer'] <= 0:
        boss_attack(b)
        b['atk_timer'] = b['interval'] * (0.65 if b['enraged'] else 1.0)


def boss_melee(b):
    """Быстрый удар вблизи: короткий телеграф, сдвиг к игроку, урон по области."""
    t = Vec3(b['ent'].position)
    dmg = b['melee_dmg'] * (1.3 if b['enraged'] else 1.0)
    b['pause'] = 0.5
    Zone(t, radius=b['melee_range'], delay=0.5, dmg=dmg)
    b['ent'].color = color.rgb32(255, 90, 90)
    invoke(safe_color, b['ent'], b['base_color'], delay=0.28)
    d = flat(player.position - t)
    if d.length() > 0.1:
        invoke(dash_boss, b, d.normalized(), 1.2, delay=0.22)
    if not b['taught']:
        b['taught'] = True
        say('Босс бьёт вблизи — не стой вплотную!', 1.6, color.rgb32(255, 150, 140))


def boss_ranged(b):
    """Дистанционная атака: снаряды, которые надо обходить, а не пережидать."""
    t = Vec3(b['ent'].position)
    d = flat(player.position - t)
    if d.length() < 0.1:
        d = Vec3(0, 0, -1)
    d = d.normalized()
    dmg = b['ranged_dmg'] * (1.3 if b['enraged'] else 1.0)
    kind = b['ranged_kind']
    b['pause'] = 0.3

    if kind == 'volley':
        for ang in (-10, 0, 10):
            dd = rotate_dir(d, ang)
            Bolt(t + Vec3(0, 0.25, 0) + dd * 1.2, dd, dmg, friendly=False,
                 speed=15, life=2.6, col=color.rgb32(225, 235, 255), size=0.42)
    elif kind == 'fire':
        for off, sp in ((-4, 11.0), (4, 13.0)):
            dd = rotate_dir(d, off)
            Bolt(t + Vec3(0, 0.3, 0) + dd * 1.2, dd, dmg, friendly=False,
                 speed=sp, life=3.0, col=color.rgb32(255, 140, 60), size=0.75)
    else:
        Bolt(t + Vec3(0, 0.25, 0) + d * 1.2, d, dmg, friendly=False,
             speed=20, life=2.2, col=color.rgb32(190, 140, 255), size=0.55)


def boss_attack(b):
    t = Vec3(b['ent'].position)
    p = Vec3(player.position)
    kind = b['kind']
    b['n'] += 1
    dmg = b['dmg'] * (1.3 if b['enraged'] else 1.0)
    b['pause'] = 0.0
    b['melee_cd'] = max(b['melee_cd'], 1.0)   # не наказываем дважды подряд

    # лёгкая анимация замаха
    b['ent'].scale = b['ent'].scale * 1.12
    invoke(safe_scale, b['ent'], b['ent'].scale / 1.12, delay=0.3)

    if kind == 'hammer':
        Zone(p, radius=3.3, delay=1.0, dmg=dmg)
    elif kind == 'spear':
        d = flat(p - t)
        if d.length() < 0.1:
            d = Vec3(0, 0, -1)
        d = d.normalized()
        Zone(t, shape='line', end=t + d * 16, width=2.0, delay=0.85, dmg=dmg)
        invoke(dash_boss, b, d, 5.0, delay=0.85)
    elif kind == 'trickster':
        teleport_boss(b)
        t = Vec3(b['ent'].position)
        if b['hp'] < b['max_hp'] * 0.5:
            Zone(Vec3(-HALF, 0, p.z), shape='line', end=Vec3(HALF, 0, p.z), width=1.7, delay=0.95, dmg=dmg)
            Zone(Vec3(p.x, 0, -HALF), shape='line', end=Vec3(p.x, 0, HALF), width=1.7, delay=1.15, dmg=dmg)
        else:
            if random.random() < 0.5:
                Zone(Vec3(-HALF, 0, p.z), shape='line', end=Vec3(HALF, 0, p.z), width=1.8, delay=0.95, dmg=dmg)
            else:
                Zone(Vec3(p.x, 0, -HALF), shape='line', end=Vec3(p.x, 0, HALF), width=1.8, delay=0.95, dmg=dmg)
    elif kind == 'dancer':
        if b['n'] % 3 == 0:
            d = flat(p - t)
            d = d.normalized() if d.length() > 0.1 else Vec3(0, 0, -1)
            Zone(t, shape='line', end=t + d * 14, width=2.4, delay=0.9, dmg=dmg + 4)
            invoke(dash_boss, b, d, 4.5, delay=0.9)
        else:
            Zone(t, radius=3.6, delay=0.8, dmg=dmg)
    elif kind == 'king':
        if b['n'] % 3 == 0:
            Zone(p, radius=4.3, delay=1.2, dmg=dmg + 5)
        else:
            Zone(t, radius=2.9, delay=0.75, dmg=dmg)
    elif kind == 'abyss':
        if b['n'] % 3 == 0:
            for i in (-0.18, 0, 0.18):
                d = flat(p - t)
                d = d.normalized() if d.length() > 0.1 else Vec3(0, 0, -1)
                rot = math.radians(i * 90)
                dd = Vec3(d.x * math.cos(rot) - d.z * math.sin(rot), 0, d.x * math.sin(rot) + d.z * math.cos(rot))
                Bolt(t + Vec3(0, 0.2, 0) + dd * 1.2, dd, dmg, friendly=False, speed=17, life=2.4)
        else:
            target = Vec3(p)
            Zone(target, radius=2.9, delay=1.1, dmg=dmg)
            invoke(teleport_boss_to, b, target, delay=1.05)


def dash_boss(b, d, dist):
    if not b['alive'] or UI_STATE != 'game':
        return
    try:
        b['ent'].position = clamp_arena(b['ent'].position + d * dist)
    except Exception:
        pass


def teleport_boss(b):
    for _ in range(30):
        pos = Vec3(random.uniform(-HALF + 2, HALF - 2), b['home_y'], random.uniform(-HALF + 2, HALF - 2))
        if dist2(pos, player.position) > 4.0:
            b['ent'].position = pos
            return


def teleport_boss_to(b, pos):
    if not b['alive'] or UI_STATE != 'game':
        return
    b['ent'].position = Vec3(pos.x, b['home_y'], pos.z)


def kill_boss(b):
    if not b['alive']:
        return
    b['alive'] = False
    Ring(Vec3(b['ent'].position.x, 0, b['ent'].position.z), 0, 3.0)
    destroy(b['ent'])
    destroy(b['ring'])
    say(f'{b["name"]} повержен!', 1.8, color.rgb32(140, 255, 180))

    alive = [x for x in ST['bosses'] if x['alive']]
    if len(alive) == 1 and len(ST['bosses']) == 2:
        other = alive[0]
        if not other['enraged']:
            other['enraged'] = True
            other['dmg'] *= 1.3
            other['interval'] *= 0.65
            other['base_color'] = color.rgb32(255, 90, 90)
            other['ent'].color = other['base_color']
            say(f'{other["name"]} впадает в ярость!', 1.8, color.rgb32(255, 120, 90))

    if not any(x['alive'] for x in ST['bosses']):
        invoke(floor_cleared, delay=0.6)
# ------------------------------------------------------------------ забег и этажи
def clear_entities():
    for b in ST['bosses']:
        for key in ('ent', 'ring'):
            try:
                if b.get(key):
                    destroy(b[key])
            except Exception:
                pass
    ST['bosses'] = []
    for z in list(ST['telegraphs']):
        try:
            destroy(z)
        except Exception:
            pass
    ST['telegraphs'] = []
    for p in list(ST['projectiles']):
        try:
            destroy(p)
        except Exception:
            pass
    ST['projectiles'] = []
    hide_reward_ui()


def apply_style():
    """Базовые бонусы выбранного стиля боя."""
    sid = ST.get('style', 'ranger')
    if sid == 'storm':
        P['dash_cd_max'] = 2.5          # очередь любит мобильность
    elif sid == 'shotgun':
        P['max_hp'] = 120               # ближний бой — больше запаса
        P['hp'] = 120
    elif sid == 'blade':
        P['speed'] *= 1.15              # нужно быстро входить в контакт
        P['dash_cd_max'] = 2.6


def new_run():
    global shake, msg_timer
    shake = 0
    msg_timer = 0
    ui_center.text = ''
    ui_center_bg.enabled = False
    ui_msg.text = ''
    P.update({
        'hp': 100, 'max_hp': 100, 'speed': 7.0, 'dmg': 14,
        'fire_cd': 0.0, 'fire_rate': 0.26, 'fire_cd_max': 0.26,
        'dash_cd': 0.0, 'dash_cd_max': 3.0, 'iframe': 0.0,
        'shield_t': 0.0, 'shield_cd': 0.0, 'shield_cd_max': 12.0, 'shield_max': 4.0,
        'shield_mult': 0.4, 'blast_cd': 0.0, 'blast_cd_max': 8.0, 'blast_dmg': 45,
        'lifesteal': 0.0, 'crit': 0.0, 'dmg_mult': 1.0,
    })
    apply_style()
    clear_entities()
    ST['floor'] = 0
    ST['relics'] = []
    ST['choices'] = []
    ST['order'] = random.sample(BOSS_KINDS, FLOORS)
    ST['phase'] = 'fight'
    player.position = Vec3(0, 0.9, 7)
    cam_target.position = player.position
    start_floor()


def start_floor():
    ST['floor'] += 1
    if ST['floor'] > FLOORS:
        win()
        return
    kind = ST['order'][ST['floor'] - 1]
    ST['bosses'] = make_bosses(kind, ST['floor'])
    ST['phase'] = 'fight'
    player.position = Vec3(0, 0.9, 7)
    cam_target.position = player.position
    P['hp'] = min(P['max_hp'], P['hp'] + int(P['max_hp'] * 0.25))
    P['dash_cd'] = P['blast_cd'] = P['shield_cd'] = 0.0
    say(f'Этаж {ST["floor"]}: {BOSS_NAMES[kind]}', 2.6, color.rgb32(255, 210, 150))


def floor_cleared():
    if ST['phase'] != 'fight':
        return
    if ST['floor'] >= FLOORS:
        win()
        return
    pool = [r for r in RELICS if r not in ST['relics']]
    random.shuffle(pool)
    ST['choices'] = pool[:3]
    ST['phase'] = 'reward'
    show_reward_ui()


def die():
    if ST['phase'] in ('dead', 'win'):
        return
    ST['phase'] = 'dead'
    ui_center.text = 'ВЫ ПОГИБЛИ\n\nEnter — новый забег     Esc — меню'
    ui_center.color = color.rgb32(255, 120, 140)
    ui_center_bg.enabled = True


def win():
    ST['phase'] = 'win'
    ui_center.text = 'ПОДЗЕМЕЛЬЕ ПРОЙДЕНО!\n\nEnter — новый забег     Esc — меню'
    ui_center.color = color.rgb32(255, 220, 130)
    ui_center_bg.enabled = True


# ------------------------------------------------------------------ экран реликвий
def show_reward_ui():
    hide_reward_ui()
    ST['reward_ui'] = []
    bg = Entity(parent=camera.ui, model='quad', scale=(2.2, 1.3), z=2, color=color.rgba32(4, 6, 12, 225))
    ST['reward_ui'].append(bg)
    title = Text(parent=camera.ui, text=f'Этаж {ST["floor"]} пройден.\nВыберите реликвию (1-3)',
                 position=(0, 0.22), origin=(0, 0), scale=1.15, color=color.rgb32(255, 220, 160), z=1)
    ST['reward_ui'].append(title)
    for i, rid in enumerate(ST['choices']):
        icon, name, desc = RELICS[rid]
        b = Button(parent=camera.ui, text=f'{icon}  {name}\n{desc}',
                   scale=(0.3, 0.14), position=(-0.34 + i * 0.34, -0.02),
                   color=color.rgba32(34, 44, 74, 240), highlight_color=color.rgba32(60, 80, 130, 240))
        b.text_entity.scale *= 0.75
        b.on_click = (lambda idx=i: pick_reward(idx))
        ST['reward_ui'].append(b)
        ST['reward_ui'].append(b.text_entity)


def hide_reward_ui():
    for e in ST.get('reward_ui', []):
        try:
            destroy(e)
        except Exception:
            pass
    ST['reward_ui'] = []


def pick_reward(i):
    if ST['phase'] != 'reward' or i < 0 or i >= len(ST['choices']):
        return
    rid = ST['choices'][i]
    apply_relic(rid)
    hide_reward_ui()
    start_floor()


# ------------------------------------------------------------------ камера и UI
def update_camera(dt):
    global shake, CAM_FWD, CAM_RIGHT, YAW, PITCH

    if CAM_MODE != 'top' and mouse.locked and not TEST:
        mx = max(-35.0, min(35.0, mouse.velocity[0] * MOUSE_SENS))
        my = max(-35.0, min(35.0, mouse.velocity[1] * MOUSE_SENS))
        YAW += mx
        PITCH -= my
        if CAM_MODE == 'first':
            PITCH = max(-85.0, min(85.0, PITCH))
        else:
            PITCH = max(6.0, min(62.0, PITCH))

    target = player.position + Vec3(0, 0.6, 0)
    cam_target.position += (target - cam_target.position) * min(1.0, dt * 7)

    jitter = Vec3(0, 0, 0)
    if shake > 0.001:
        jitter = Vec3(random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(-1, 1)) * shake * 1.3
        shake = max(0.0, shake - dt * 2.4)

    if CAM_MODE == 'top':
        camera.position = cam_target.position + Vec3(0, 15.5, 13.0) + jitter
        camera.rotation = (50, 180, 0)
        CAM_FWD = Vec3(0, 0, -1)
        CAM_RIGHT = Vec3(-1, 0, 0)
        aim = flat(aim_point() - player.position)
        if aim.length() > 0.05:
            player.rotation_y = math.degrees(math.atan2(aim.x, aim.z))
        return

    camera.rotation = (PITCH, YAW, 0)
    player.rotation_y = YAW
    fwd = flat(camera.forward)
    right = flat(camera.right)
    fwd = fwd.normalized() if fwd.length() > 0.01 else Vec3(0, 0, -1)
    right = right.normalized() if right.length() > 0.01 else Vec3(-1, 0, 0)
    CAM_FWD, CAM_RIGHT = fwd, right

    if CAM_MODE == 'first':
        camera.position = cam_target.position + Vec3(0, PLAYER_EYE, 0) + jitter
        return

    # от третьего лица: камера на «журавле» позади игрока, прицел чуть выше
    height = THIRD_DIST * math.tan(math.radians(PITCH))
    pivot = cam_target.position + Vec3(0, 0.5, 0)
    camera.position = pivot - fwd * THIRD_DIST + Vec3(0, height, 0) + jitter
    camera.rotation = (max(2.0, PITCH - THIRD_LIFT), YAW, 0)


def update_ability_icons():
    """Перезарядка и глоу: готовые способности подсвечиваются и пульсируют."""
    dt = min(0.05, time.dt)
    now = time.time()

    def upd(kind, cur, mx):
        ic = ABILITY_ICONS[kind]
        frac = 0.0 if mx <= 0.001 else max(0.0, min(1.0, cur / mx))
        ready = frac <= 0.004

        # момент восстановления — короткая яркая вспышка
        if ready and not ic['ready']:
            ic['pulse'] = 0.55
        elif not ready:
            ic['pulse'] = 0.0
        ic['ready'] = ready

        if ready:
            if ic['overlay'].enabled:
                ic['overlay'].enabled = False
            if ic['text'].text:
                ic['text'].text = ''

            # глоу: затухающая вспышка + мягкое «дыхание»
            ic['pulse'] = max(0.0, ic['pulse'] - dt)
            kick = ic['pulse'] / 0.55
            breath = 0.5 + 0.5 * math.sin(now * 4.0 + ic['phase'])
            s = 1.08 + 0.28 * kick + 0.04 * breath
            ic['glow'].scale = (s, s)
            ic['glow'].enabled = True
            r, g, b = ic['rgb']
            ic['halo_out'].color = color.rgba(
                r, g, b, min(1.0, 0.20 + 0.10 * breath + 0.30 * kick))
            ic['halo_in'].color = color.rgba(
                r, g, b, min(1.0, 0.30 + 0.12 * breath + 0.34 * kick))
            ic['frame'].color = color.rgba(
                r, g, b, min(1.0, 0.62 + 0.24 * breath + 0.14 * kick))
            return

        h = 0.084 * frac
        if not ic['overlay'].enabled:
            ic['overlay'].enabled = True
        ic['overlay'].scale_y = h
        ic['text'].text = f'{cur:.1f}'
        r, g, b = ic['rgb']
        ic['frame'].color = color.rgba(r, g, b, 0.30)
        if ic['glow'].enabled:
            ic['glow'].enabled = False

    upd('fire', P['fire_cd'], P['fire_cd_max'])
    upd('dash', P['dash_cd'], P['dash_cd_max'])
    upd('blast', P['blast_cd'], P['blast_cd_max'])
    upd('shield', P['shield_cd'], P['shield_cd_max'])


def update_ui():
    hp_pct = max(0.0, P['hp'] / P['max_hp'])
    ui_hp.scale_x = hp_pct
    ui_hp.color = color.rgb32(255, 72, 104) if hp_pct > 0.35 else color.rgb32(255, 40, 60)
    ui_hp_txt.text = f'{int(P["hp"])} / {int(P["max_hp"])}'

    alive = [b for b in ST['bosses'] if b['alive']]
    ui_boss_bg.enabled = bool(alive)
    if alive:
        b = alive[0]
        ui_boss.scale_x = max(0.0, b['hp'] / b['max_hp'])
        extra = f'  (+{len(alive) - 1})' if len(alive) > 1 else ''
        ui_boss_txt.text = f'{b["name"]}{extra}   {max(0, int(b["hp"]))} / {int(b["max_hp"])}'
    else:
        ui_boss.scale_x = 0
        ui_boss_txt.text = ''

    ui_floor.text = f'Этаж {min(ST["floor"], FLOORS)} / {FLOORS}'
    update_ability_icons()

    ui_relics.text = '  '.join(RELICS[r][0] for r in ST['relics'])
    ui_mode.text = f'Камера: {MODE_NAMES[CAM_MODE]}   (V — сменить, Esc — меню)'
    ui_style.text = 'Стиль: ' + STYLES[ST.get('style', 'ranger')]['name']
    show_cross = (CAM_MODE != 'top' and ST['phase'] == 'fight')
    cross_h.enabled = show_cross
    cross_v.enabled = show_cross


# ------------------------------------------------------------------ меню и настройки
PALETTE = {
    'panel': color.rgba32(8, 11, 21, 246),
    'btn': color.rgba32(32, 44, 74, 246),
    'btn_hi': color.rgba32(60, 82, 132, 246),
    'sel': color.rgba32(92, 126, 196, 246),
    'gold': color.rgb32(255, 220, 160),
    'dim': color.rgb32(140, 152, 192),
}

menu_root = Entity(parent=camera.ui, enabled=False)
settings_root = Entity(parent=camera.ui, enabled=False)
pause_root = Entity(parent=camera.ui, enabled=False)
style_root = Entity(parent=camera.ui, enabled=False)
UI_SLIDERS = {}
UI_VIEW_BUTTONS = {}


def _panel(root, w=1.06, h=0.94):
    Entity(parent=root, model='quad', scale=(w, h), z=3, color=PALETTE['panel'])
    Entity(parent=root, model='quad', scale=(w, 0.006), y=h * 0.40, z=2,
           color=color.rgba32(255, 190, 110, 150))


def _menu_button(root, text, y, on_click, w=0.42, h=0.085, x=0.0, scale_text=0.92):
    kwargs = {}
    if on_click is not None:
        kwargs['on_click'] = on_click
    b = Button(parent=root, text=text, scale=(w, h), position=(x, y),
               color=PALETTE['btn'], highlight_color=PALETTE['btn_hi'], **kwargs)
    try:
        b.text_entity.scale *= scale_text
    except Exception:
        pass
    return b


def _open_settings(back):
    global UI_STATE, UI_BACK
    UI_BACK = back
    UI_STATE = 'settings'
    menu_root.enabled = False
    pause_root.enabled = False
    style_root.enabled = False
    settings_root.enabled = True
    sync_settings_sliders()
    refresh_view_buttons()
    lock_mouse(force=True)


def open_settings_from_menu():
    _open_settings('menu')


def open_settings_from_pause():
    _open_settings('paused')


def close_settings():
    global UI_STATE
    save_settings()
    settings_root.enabled = False
    if UI_BACK == 'paused':
        UI_STATE = 'paused'
        pause_root.enabled = True
    else:
        UI_STATE = 'menu'
        menu_root.enabled = True
    lock_mouse(force=True)


def on_sens_changed():
    global MOUSE_SENS
    try:
        SETTINGS['sens'] = float(round(UI_SLIDERS['sens'].value, 0))
    except Exception:
        return
    MOUSE_SENS = SETTINGS['sens']


def on_fov_changed():
    try:
        SETTINGS['fov'] = float(round(UI_SLIDERS['fov'].value, 0))
    except Exception:
        return
    camera.fov = SETTINGS['fov']


def refresh_view_buttons():
    for mode, b in UI_VIEW_BUTTONS.items():
        try:
            b.color = PALETTE['sel'] if SETTINGS['view'] == mode else PALETTE['btn']
        except Exception:
            pass


def choose_view(mode):
    SETTINGS['view'] = mode
    set_mode(mode)
    refresh_view_buttons()
    save_settings()


def sync_settings_sliders():
    try:
        UI_SLIDERS['sens'].value = SETTINGS['sens']
        UI_SLIDERS['fov'].value = SETTINGS['fov']
    except Exception:
        pass


def reset_settings():
    SETTINGS.update(DEFAULT_SETTINGS)
    apply_settings()
    set_mode(SETTINGS['view'])
    sync_settings_sliders()
    refresh_view_buttons()
    save_settings()


def build_menu():
    _panel(menu_root)
    Text(parent=menu_root, text='ПОДЗЕМЕЛЬЕ БОССОВ 3D', position=(0, 0.33), origin=(0, 0),
         scale=2.0, color=PALETTE['gold'])
    Text(parent=menu_root, text='роглайк-арена • 5 этажей • 5 боссов', position=(0, 0.245),
         origin=(0, 0), scale=0.85, color=PALETTE['dim'])
    _menu_button(menu_root, 'Играть', 0.10, open_style_select)
    _menu_button(menu_root, 'Настройки', -0.02, open_settings_from_menu)
    _menu_button(menu_root, 'Выход', -0.14, application.quit)
    Text(parent=menu_root, text='WASD — движение     ЛКМ — огонь     Space — рывок     V — камера',
         position=(0, -0.30), origin=(0, 0), scale=0.72, color=color.rgb32(110, 122, 160))


def build_settings():
    _panel(settings_root)
    Text(parent=settings_root, text='НАСТРОЙКИ', position=(0, 0.34), origin=(0, 0),
         scale=1.7, color=PALETTE['gold'])

    Text(parent=settings_root, text='Чувствительность мыши', position=(-0.40, 0.20),
         origin=(-0.5, 0), scale=0.95, color=color.rgb32(200, 210, 240))
    UI_SLIDERS['sens'] = Slider(40, 300, default=SETTINGS['sens'], step=1, dynamic=True,
                                parent=settings_root, x=-0.38, y=0.14,
                                bar_color=color.rgba32(46, 58, 92, 255))
    UI_SLIDERS['sens'].label.text = ''
    UI_SLIDERS['sens'].on_value_changed = on_sens_changed

    Text(parent=settings_root, text='Угол обзора (FOV)', position=(-0.40, 0.02),
         origin=(-0.5, 0), scale=0.95, color=color.rgb32(200, 210, 240))
    UI_SLIDERS['fov'] = Slider(50, 100, default=SETTINGS['fov'], step=1, dynamic=True,
                               parent=settings_root, x=-0.38, y=-0.04,
                               bar_color=color.rgba32(46, 58, 92, 255))
    UI_SLIDERS['fov'].label.text = ''
    UI_SLIDERS['fov'].on_value_changed = on_fov_changed

    Text(parent=settings_root, text='Вид по умолчанию', position=(-0.40, -0.105),
         origin=(-0.5, 0), scale=0.95, color=color.rgb32(200, 210, 240))
    for i, (mode, label) in enumerate((('third', '3-е лицо'),
                                       ('first', '1-е лицо'),
                                       ('top', 'Сверху'))):
        b = _menu_button(settings_root, label, -0.155, None, w=0.20, h=0.07,
                         x=-0.38 + i * 0.24, scale_text=0.8)
        b.on_click = (lambda m=mode: choose_view(m))
        UI_VIEW_BUTTONS[mode] = b
    refresh_view_buttons()

    _menu_button(settings_root, 'Сброс', -0.255, reset_settings, w=0.24, h=0.075, x=-0.14)
    _menu_button(settings_root, 'Назад', -0.255, close_settings, w=0.30, h=0.075, x=0.20)


def build_pause():
    _panel(pause_root, 0.9, 0.86)
    Text(parent=pause_root, text='ПАУЗА', position=(0, 0.27), origin=(0, 0),
         scale=1.7, color=PALETTE['gold'])
    _menu_button(pause_root, 'Продолжить', 0.08, resume_game)
    _menu_button(pause_root, 'Настройки', -0.04, open_settings_from_pause)
    _menu_button(pause_root, 'В главное меню', -0.16, quit_to_menu, w=0.46)
    Text(parent=pause_root, text='Esc — продолжить игру', position=(0, -0.30),
         origin=(0, 0), scale=0.75, color=color.rgb32(110, 122, 160))


def _style_card(sid, x):
    st = STYLES[sid]
    text = f"{st['name']}\n{st['line']}\n{st['stats']}\n{st['note']}"
    b = Button(parent=style_root, text=text, scale=(0.34, 0.36), position=(x, 0.02),
               color=color.rgba32(26, 34, 56, 246),
               highlight_color=color.rgba32(52, 70, 112, 246))
    b.text_entity.scale *= 0.66
    c0, c1, c2 = st['color'][0], st['color'][1], st['color'][2]
    Entity(parent=b, model='quad', scale=(0.88, 0.05), y=0.46, z=-1,
           color=color.rgba(c0, c1, c2, 0.85))
    b.on_click = (lambda s=sid: start_game(s))


def build_style():
    _panel(style_root, 1.72, 0.94)
    Text(parent=style_root, text='ВЫБЕРИТЕ СТИЛЬ БОЯ', position=(0, 0.37), origin=(0, 0),
         scale=1.6, color=PALETTE['gold'])
    Text(parent=style_root, text='Стиль меняет только атаку на ЛКМ. Рывок, взрыв и щит общие для всех.',
         position=(0, 0.29), origin=(0, 0), scale=0.85, color=PALETTE['dim'])
    for i, sid in enumerate(STYLE_ORDER):
        _style_card(sid, -0.57 + i * 0.38)
    _menu_button(style_root, 'Назад', -0.30, show_main_menu, w=0.26, h=0.075)
    Text(parent=style_root, text='1-4 — быстрый выбор     Esc — назад', position=(0, -0.385),
         origin=(0, 0), scale=0.72, color=color.rgb32(110, 122, 160))


def open_style_select():
    global UI_STATE, msg_timer
    menu_root.enabled = False
    settings_root.enabled = False
    pause_root.enabled = False
    style_root.enabled = True
    UI_STATE = 'style'
    set_hud_visible(False)
    # убираем экран смерти/победы, чтобы он не просвечивал сквозь карточки
    ui_center.text = ''
    ui_center_bg.enabled = False
    ui_msg.text = ''
    msg_timer = 0.0
    lock_mouse(force=True)


def show_main_menu():
    global UI_STATE, msg_timer
    clear_entities()
    ST['phase'] = 'menu'
    ui_center.text = ''
    ui_center_bg.enabled = False
    ui_msg.text = ''
    msg_timer = 0.0
    pause_root.enabled = False
    settings_root.enabled = False
    style_root.enabled = False
    menu_root.enabled = True
    UI_STATE = 'menu'
    set_hud_visible(False)
    lock_mouse(force=True)


def start_game(style_id=None):
    global UI_STATE
    if style_id in STYLES:
        ST['style'] = style_id
    menu_root.enabled = False
    settings_root.enabled = False
    style_root.enabled = False
    pause_root.enabled = False
    UI_STATE = 'game'
    set_hud_visible(True)
    set_mode(SETTINGS['view'])
    new_run()
    lock_mouse(force=True)


def pause_game():
    global UI_STATE
    if UI_STATE != 'game':
        return
    UI_STATE = 'paused'
    pause_root.enabled = True
    # убираем боевые подсказки и прицел, чтобы не просвечивали сквозь панель
    ui_msg.enabled = False
    cross_h.enabled = False
    cross_v.enabled = False
    lock_mouse(force=True)


def resume_game():
    global UI_STATE
    if UI_STATE != 'paused':
        return
    UI_STATE = 'game'
    pause_root.enabled = False
    ui_msg.enabled = True
    lock_mouse(force=True)


def quit_to_menu():
    pause_root.enabled = False
    show_main_menu()


def update_menu_camera(dt):
    global MENU_ANGLE
    MENU_ANGLE = (MENU_ANGLE + dt * 6.0) % 360
    a = math.radians(MENU_ANGLE)
    camera.position = Vec3(math.sin(a) * 18.0, 7.5, math.cos(a) * 18.0)
    camera.rotation = (22, MENU_ANGLE + 180, 0)


build_menu()
build_settings()
build_pause()
build_style()


# ------------------------------------------------------------------ главный цикл
def update():
    global msg_timer
    dt = min(0.05, time.dt)

    if UI_STATE == 'menu':
        update_menu_camera(dt)
        return
    if UI_STATE == 'style':
        update_menu_camera(dt * 0.5)
        return
    if UI_STATE == 'settings':
        if UI_BACK == 'menu':
            update_menu_camera(dt * 0.5)
        return
    if UI_STATE == 'paused':
        return

    lock_mouse()

    if msg_timer > 0:
        msg_timer -= dt
        if msg_timer <= 0:
            ui_msg.text = ''

    update_camera(dt)

    if ST['phase'] == 'fight':
        mv = move_dir()
        if mv.length() > 0:
            player.position = clamp_arena(player.position + mv * P['speed'] * dt)
        player_ring.position = Vec3(player.position.x, 0.03, player.position.z)

        P['fire_cd'] = max(0.0, P['fire_cd'] - dt)
        P['dash_cd'] = max(0.0, P['dash_cd'] - dt)
        P['blast_cd'] = max(0.0, P['blast_cd'] - dt)
        P['shield_cd'] = max(0.0, P['shield_cd'] - dt)
        P['iframe'] = max(0.0, P['iframe'] - dt)
        if P['shield_t'] > 0:
            P['shield_t'] = max(0.0, P['shield_t'] - dt)
            player_ring.color = color.rgba32(90, 200, 255, 130)
        elif player_ring.color != color.rgba32(77, 225, 255, 70):
            player_ring.color = color.rgba32(77, 225, 255, 70)

        for b in ST['bosses']:
            update_boss(b, dt)

    update_ui()


# ------------------------------------------------------------------ тест-режим
if TEST:
    import os
    from panda3d.core import Filename

    def snap(name):
        base.win.saveScreenshot(Filename.fromOsSpecific(os.path.abspath(name)))

    # маркеры осей для проверки ориентации камеры (только в тесте)
    Entity(model='cube', color=color.rgb32(255, 40, 40), position=(0, 3, -4), scale=1.0)    # красный = даль (-Z)
    Entity(model='cube', color=color.rgb32(40, 255, 40), position=(4, 1, 7), scale=0.7)     # зелёный = +X
    Entity(model='cube', color=color.rgb32(255, 255, 40), position=(-4, 1, 7), scale=0.7)   # жёлтый = -X

    def _u1():
        snap('test_menu.png')
        print('U1 menu', UI_STATE, flush=True)
        open_settings_from_menu()
        invoke(_u2, delay=0.6)

    def _u2():
        snap('test_settings.png')
        print('U2 settings', UI_STATE, SETTINGS['sens'], SETTINGS['fov'], flush=True)
        # проверим, что слайдеры меняют настройки
        UI_SLIDERS['sens'].value = 160
        UI_SLIDERS['fov'].value = 75
        print('U2 applied', round(MOUSE_SENS, 1), round(camera.fov, 1), flush=True)
        close_settings()
        invoke(_u3, delay=0.4)

    def _u3():
        open_style_select()
        print('U3 style screen', UI_STATE, flush=True)
        invoke(_u3b, delay=0.6)

    def _u3b():
        snap('test_style.png')
        print('U3b style shot', UI_STATE, flush=True)
        start_game('storm')
        print('U3 game', UI_STATE, ST['phase'], ST['style'], flush=True)
        invoke(_p1, delay=0.8)

    def _p1():
        pause_game()
        invoke(_p2, delay=0.5)

    def _p2():
        snap('test_pause.png')
        print('U4 pause', UI_STATE, flush=True)
        resume_game()
        invoke(_m1, delay=0.4)

    def _m1():
        snap('test_view_third.png')
        print('M1 third', flush=True)
        invoke(_m2, delay=0.4)

    def _m2():
        set_mode('first')
        invoke(_m3, delay=0.4)

    def _m3():
        snap('test_view_first.png')
        print('M2 first', flush=True)
        set_mode('top')
        invoke(_m4, delay=0.4)

    def _m4():
        snap('test_axes.png')
        print('M3 top', flush=True)
        invoke(_t1a, delay=0.25)

    def _t1a():
        """Проверка ближних и дальних атак у всех типов боссов."""
        try:
            rows = []
            for kind in BOSS_KINDS:
                for b in make_bosses(kind, 1):
                    b['taught'] = True
                    z0 = len(ST['telegraphs'])
                    boss_melee(b)
                    melee_z = len(ST['telegraphs']) - z0
                    bolt_n = 0
                    if b['ranged_kind']:
                        b0 = sum(1 for e in list(scene.entities)
                                 if isinstance(e, Bolt) and not e.friendly)
                        boss_ranged(b)
                        bolt_n = sum(1 for e in list(scene.entities)
                                     if isinstance(e, Bolt) and not e.friendly) - b0
                    rows.append((kind, melee_z, bolt_n))
                    destroy(b['ent'])
                    destroy(b['ring'])
            for z in list(ST['telegraphs']):
                try:
                    destroy(z)
                except Exception:
                    pass
            ST['telegraphs'] = []
            for e in list(scene.entities):
                if isinstance(e, Bolt):
                    destroy(e)
            print('T1a ai', rows, flush=True)
        except Exception:
            import traceback
            traceback.print_exc()
        invoke(_t1, delay=0.2)

    def _t1():
        try:
            for sid in STYLE_ORDER:
                ST['style'] = sid
                P['fire_cd'] = 0.0
                shoot()
                P['fire_cd'] = 0.0
            ST['style'] = 'storm'
            blast()
            dash()
            use_shield()
            for b in ST['bosses']:
                boss_attack(b)
                boss_melee(b)
                if b['ranged_kind']:
                    boss_ranged(b)
            print('T1 ok', [b['kind'] for b in ST['bosses']], len(ST['telegraphs']), flush=True)
            snap('test_boss_ai.png')
            print('T1 ai shot', flush=True)
        except Exception:
            import traceback
            traceback.print_exc()
        invoke(_t1b, delay=1.0)

    def _t1b():
        snap('test_abilities.png')
        print('T1b ability icons', flush=True)
        P['fire_cd'] = P['dash_cd'] = P['blast_cd'] = P['shield_cd'] = 0.0
        invoke(_t1c, delay=0.12)

    def _t1c():
        snap('test_ability_glow.png')
        print('T1c ability glow', flush=True)
        invoke(_t2, delay=0.2)

    def _t2():
        try:
            for b in ST['bosses']:
                if b['alive']:
                    damage_boss(b, 99999)
            print('T2 kill ok', flush=True)
            invoke(_t3, delay=1.2)
        except Exception:
            import traceback
            traceback.print_exc()
            application.quit()

    def _t3():
        try:
            snap('test_reward.png')
            print('T3 reward', ST['phase'], [c for c in ST.get('choices', [])], flush=True)
            pick_reward(0)
            print('T3 next floor', ST['floor'], ST['phase'], flush=True)
            invoke(_t4, delay=1.2)
        except Exception:
            import traceback
            traceback.print_exc()
            application.quit()

    def _t4():
        try:
            P['hp'] = 1
            P['shield_t'] = 0
            hurt_player(999)
            print('T4 dead', ST['phase'], flush=True)
            invoke(_t5, delay=0.8)
        except Exception:
            import traceback
            traceback.print_exc()
            application.quit()

    def _t5():
        try:
            snap('test_dead.png')
            input('enter')
            print('T5 after death', UI_STATE, flush=True)
            print('TEST_SHOT_OK', flush=True)
        except Exception:
            import traceback
            traceback.print_exc()
        application.quit()

    apply_settings()
    show_main_menu()
    invoke(_u1, delay=0.9)
else:
    apply_settings()
    show_main_menu()

app.run()



