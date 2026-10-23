# 本地数据：所有作品存在 data/作品.json，封面图存在 data/封面/<作品id>.jpg
import os, sys, json, uuid

# 打包成 exe 时：数据、设置放在 exe 旁边；自带的图标在解包目录（RES）里
HERE = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
RES = getattr(sys, '_MEIPASS', HERE)
DATA_DIR = os.path.join(HERE, 'data')
SETTINGS = os.path.join(HERE, 'settings.json')

CATEGORIES = ['文学作品', '音乐', '小说', '电视剧', '电影', '动漫', '综艺', '鬼畜/梗', '游戏']
MAX_RATING = 10


def data_file():
    return os.path.join(DATA_DIR, '作品.json')


def cover_dir():
    return os.path.join(DATA_DIR, '封面')


def cover_path(work):
    """作品的封面文件路径；没有封面返回 None。"""
    if not work.get('cover'):
        return None
    p = os.path.join(cover_dir(), work['cover'])
    return p if os.path.isfile(p) else None


def new_id():
    return uuid.uuid4().hex[:12]


def new_work(year, category, title='', author=''):
    return {'id': new_id(), 'year': year, 'category': category, 'title': title, 'author': author,
            'rating': 0, 'comment': '', 'cover': ''}


def empty_doc():
    return {'version': 1, 'categories': list(CATEGORIES), 'years': [], 'works': []}


def load():
    try:
        with open(data_file(), encoding='utf-8') as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return empty_doc()
    base = empty_doc()
    for k, v in base.items():
        doc.setdefault(k, v)
    for w in doc['works']:            # 手改过 json 或旧版本缺字段时补上默认值
        for k, v in new_work(w.get('year', 0), w.get('category', '')).items():
            w.setdefault(k, v)
    # 作品里出现的年份、分类，列表里一定要有
    doc['years'] = sorted(set(doc['years']) | {w['year'] for w in doc['works']}, reverse=True)
    for w in doc['works']:
        if w['category'] not in doc['categories']:
            doc['categories'].append(w['category'])
    return doc


def save(doc):
    os.makedirs(DATA_DIR, exist_ok=True)
    doc['years'] = sorted(set(doc['years']), reverse=True)
    tmp = data_file() + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, data_file())     # 先写临时文件再替换，写到一半断电也不会坏掉原文件


def load_settings():
    try:
        with open(SETTINGS, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(s):
    with open(SETTINGS, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
