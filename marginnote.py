# 从 MarginNote 导出的大纲导入作品。
# MarginNote「导出到 OmniOutliner」得到的是 gzip 压缩的 OmniOutliner XML（文件名一般是 contents.xml），也兼容 OPML。
# 导图结构：「2019内容」→「年度音乐」等分类 → 作品名；节点文字里有四位年份的就当作年份节点。
import gzip, re
import xml.etree.ElementTree as ET

OO = '{http://www.omnigroup.com/namespace/OmniOutliner/v3}'
YEAR = re.compile(r'(19|20)\d\d')
AUTHOR_CATEGORIES = {'音乐'}            # 只有这些分类把末尾括号里的内容拆成作者（歌手）；其他分类的括号多是别名，原样保留


class ImportError_(Exception):
    pass


class Node:
    def __init__(self, text, note='', children=None):
        self.text, self.note, self.children = text, note, children or []


def _oo_text(el):
    """OmniOutliner 的富文本：每段 <p> 里的 <lit> 才是文字，<style> 里的是格式，不能混进来。"""
    if el is None:
        return ''
    return '\n'.join(''.join(l.text or '' for l in p.iter(OO + 'lit')) for p in el.iter(OO + 'p')).strip()


def _oo_nodes(parent):
    nodes = []
    for it in parent.findall(OO + 'item'):
        first = it.find(OO + 'values/' + OO + 'text')
        ch = it.find(OO + 'children')
        nodes.append(Node(_oo_text(first), _oo_text(it.find(OO + 'note')), _oo_nodes(ch) if ch is not None else []))
    return nodes


def _opml_nodes(parent):
    return [Node((o.get('text') or o.get('title') or '').strip(), (o.get('_note') or '').strip(), _opml_nodes(o))
            for o in parent.findall('outline')]


def read_tree(path):
    with open(path, 'rb') as f:
        raw = f.read()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ImportError_('文件不是有效的 XML。请在 MarginNote 里用「导出到 OmniOutliner」导出')
    if root.tag == OO + 'outline' and root.find(OO + 'root') is not None:
        return _oo_nodes(root.find(OO + 'root'))
    if root.tag == 'opml' and root.find('body') is not None:
        return _opml_nodes(root.find('body'))
    raise ImportError_('认不出这个文件的格式。请在 MarginNote 里用「导出到 OmniOutliner」导出')


def clean_title(s):
    """修掉手打时常见的不配对符号：多出来的右括号删掉，只有》没有《的在前面补上《。"""
    s = ' '.join(s.split())
    out, depth = [], 0
    for c in s:
        if c in '（(':
            depth += 1
        elif c in '）)':
            if depth == 0:
                continue
            depth -= 1
        out.append(c)
    s = ''.join(out)
    if '》' in s and '《' not in s:
        s = '《' + s
    return s


def split_author(title):
    """「画（邓紫棋）」→ ('画', '邓紫棋')；没有末尾括号的原样返回。"""
    m = re.fullmatch(r'(.+?)\s*[（(]([^（）()]+)[）)]', title)
    return (m[1].strip(), m[2].strip()) if m else (title, '')


def category_name(s):
    s = s.strip()
    return s[2:].strip() if s.startswith('年度') and len(s) > 2 else s


def parse(path):
    """返回 (年份集合, 作品列表)。作品是 {year, category, title, author, comment}，按导图里的顺序。"""
    years, works = set(), []

    def visit(nodes):
        for n in nodes:
            m = YEAR.search(n.text)
            if not m:
                visit(n.children)           # 「年度总结」这种汇总节点：往下找年份
                continue
            year = int(m[0])
            years.add(year)
            for c in n.children:            # 年份 → 分类 → 作品
                cat = category_name(c.text)
                if not cat:
                    continue
                for w in c.children:
                    title = clean_title(w.text)
                    if not title:
                        continue
                    author = ''
                    if cat in AUTHOR_CATEGORIES:
                        title, author = split_author(title)
                    works.append({'year': year, 'category': cat, 'title': title, 'author': author, 'comment': w.note})

    visit(read_tree(path))
    if not years:
        raise ImportError_('没在文件里找到年份。导图的节点要像「2019内容」这样带年份，下面一层是分类，再下一层是作品')
    return years, works


def merge(doc, years, works, make_work):
    """并入 doc，返回 (新增数, 跳过的重复数)。同一年、同分类、同名同作者的算重复。"""
    have = {(w['year'], w['category'], w['title'], w['author']) for w in doc['works']}
    added = 0
    for x in works:
        key = (x['year'], x['category'], x['title'], x['author'])
        if key in have:
            continue
        have.add(key)
        w = make_work(x['year'], x['category'], x['title'], x['author'])
        w['comment'] = x['comment']
        doc['works'].append(w)
        if x['category'] not in doc['categories']:
            doc['categories'].append(x['category'])
        added += 1
    doc['years'] = sorted(set(doc['years']) | years, reverse=True)
    return added, len(works) - added
