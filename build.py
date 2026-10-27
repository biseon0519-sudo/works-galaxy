# 打包给别人用：.venv\Scripts\python.exe build.py
# 生成 dist\年度作品\（双击里面的 年度作品.exe 就能用，不用装 Python），再压成 dist\yearly-works-v<版本>.zip。
# 只打包代码和图标；data\、settings.json、log.txt 这些个人数据不会进去，朋友打开是一张空白的星图。
import os, re, shutil, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = '年度作品'
VERSION = re.search(r"VERSION = '([^']+)'", open(os.path.join(HERE, 'app.py'), encoding='utf-8').read())[1]
DIST = os.path.join(HERE, 'dist')
OUT = os.path.join(DIST, NAME)
README = f"""年度作品 v{VERSION}

记录每年喜欢的作品（文学、音乐、小说、电视剧、电影、动漫、综艺、鬼畜/梗、游戏），画成一张会动的星图：
中间是黑洞，每一年是一颗恒星，点恒星展开这一年的分类和作品。

用法：
  · 双击「年度作品.exe」。右上角「添加年份」先建一年，点那颗恒星展开，点「＋」或右键恒星添加作品，点作品可以编辑，右键可以删除。
  · 每个作品可以写作者、打 10 星评分、写短评、放封面（拖图片进去或 Ctrl+V 粘贴截图），鼠标放在作品上会显示封面。
  · 点黑洞：所有恒星被吸进去 / 再点一次放出来。全图里可以拖动恒星，拖到黑洞跟前松手会单独收进去。
  · 以前用 MarginNote 3 做过思维导图的，可以「导出到 OmniOutliner」后点「从 MarginNote 导入」。

说明：
  · 记录存在旁边的 data 文件夹里，不联网、不上传。换电脑或升级新版时，把 data 文件夹拷过去就行。
  · 画面全部用显卡画，需要支持 OpenGL 3.3 的显卡（近十年的电脑基本都行）；笔记本请接上电源、让程序用独立显卡会更流畅。
  · 打不开或出错时，旁边会生成 log.txt，把它发给作者。
"""


def res(name):
    return os.path.join(HERE, name)


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', res('app.py'), '--name', NAME, '--noconfirm', '--windowed',
                    '--icon', res('icon.ico'), '--add-data', res('icon.ico') + ';.',
                    '--hidden-import', 'glcontext.wgl',          # moderngl 运行时才按平台导入，PyInstaller 看不出来
                    '--distpath', OUT, '--workpath', os.path.join(HERE, 'build'), '--specpath', os.path.join(HERE, 'build'),
                    '--contents-directory', '运行库'], cwd=HERE, check=True)
    # PyInstaller 会多套一层 dist\年度作品\年度作品\，挪上来
    inner = os.path.join(OUT, NAME)
    for f in os.listdir(inner):
        shutil.move(os.path.join(inner, f), OUT)
    os.rmdir(inner)
    with open(os.path.join(OUT, '使用说明.txt'), 'w', encoding='utf-8-sig') as f:
        f.write(README)
    zip_path = os.path.join(DIST, f'yearly-works-v{VERSION}.zip')    # GitHub Releases 的附件名不能有中文
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(OUT):
            for f in files:
                p = os.path.join(root, f)
                z.write(p, os.path.relpath(p, DIST))
    print(f'\n完成：{zip_path}（{os.path.getsize(zip_path) / 2**20:.0f} MB）')


if __name__ == '__main__':
    main()
