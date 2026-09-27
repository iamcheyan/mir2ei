# Mir2EI · 传奇3 EI 版本游戏百科

EI 传奇3.0（英雄杀）客户端 + Mud3 服务端的**完整游戏百科静态站**，托管于 GitHub Pages：
**https://mir2ei.iamcheyan.com**

以 EI 3.0 客户端为底板、Mud3 服务端数据为权威来源，对照 Zircon / mir3ei 整理。
包含 544 张地图、534 种怪物、2203 件装备道具、218 个技能、125 位 NPC、34 个任务、
221 家商店、30 套套装，以及 NPC 位置、地图连接、怪物刷新、掉落、商店货品、
对话脚本等全量数据。

## 目录结构

```
mir2ei-website/
├── index.html             # 静态站入口 (GitHub Pages 根)
├── maps.html / map/       # 地图列表 + 每图详情 (怪物刷新/NPC/连接)
├── monsters.html / monster/  # 怪物图鉴 + 详情
├── items.html / item/     # 装备道具 + 详情
├── skills.html / skill/   # 技能
├── npcs.html / npc/       # NPC (位置/任务/对话脚本)
├── quests.html / quest/   # 任务
├── stores.html / store/   # 商店
├── sets.html / set/       # 套装
├── thumb/                 # 544 张地图缩略图
├── img/                   # 条目图标 (怪物/物品/技能/NPC)
├── data/                  # 百科数据 JSON (WikiServer 运行时输入)
├── scripts/               # 数据生成 + 静态化脚本
└── CNAME                  # mir2ei.iamcheyan.com
```

## 静态站

`index.html` 等根目录 HTML 是 **WikiServer.py 渲染的静态快照**（4175 个页面），
可直接部署到任意静态托管（GitHub Pages / Netlify / Nginx），无需后端。

### 重新生成静态站

```bash
# 1. 启动动态百科服务 (数据在 data/, 缩略图/图标需先生成)
MIR2EI_DATA=$PWD/data python3 scripts/WikiServer.py --port 8777

# 2. 静态化
python3 scripts/static_site.py --port 8777 --out _site --base ""
```

### Zircon 名称审校

审校页 `zircon-audit.html` 将 `db_names.json` 的中日文键与 `wiki_all.json`、`wiki_data_v2.json`、静态详情页和图片做逐项交叉索引。生成器只读 Zircon 检出，不覆盖百科名称或源数据；名称归一化只作候选召回，百科译名一致也不会自动标为正确。

```bash
python3 scripts/build_zircon_name_audit.py --zircon-repo /path/to/zircon
python3 scripts/integrate_zircon_names.py --source-root . --site-root . --base ""
```

`static_site.py` 会在生成 `_site` 后自动复制审校资源并加入导航。类别列表与实体页加载轻量交叉索引，原有英文名保留。人工结论和依据仅保存在当前浏览器；用“导出本地审校”备份，通过匹配同一数据指纹的 JSON 文件移交审校记录。

运行测试：`python3 -m unittest discover -s tests -v`。

## 数据生成链路

```
NAS 源 (EI客户端/Mud3服务端)
  ├─ scripts/rebuild_tmp.py         → report_full.json (地图/刷怪/商人/守卫)
  ├─ scripts/wiki_build.py          → wiki_data.json  (百科视图数据)
  ├─ scripts/three_versions_check.py→ three_versions.json (三版本交叉)
  ├─ scripts/dat_integrate.py       → wiki_dat.json   (老版 DAT 条目)
  ├─ scripts/dump_all_fix.py        → wiki_all.json   (System.db 全表)
  ├─ scripts/build_wiki_images.py   → wiki_images.json(条目图片帧映射)
  ├─ scripts/ver_tags.py            → wiki_data_v2.json (版本标签+图片引用)
  ├─ scripts/build_stores.py + stores_build.py → wiki_stores.json (商店)
  └─ scripts/map_routes.py          → map_links.json  (地图连接)
```

脚本需要环境变量指向数据源（NAS 路径），本地重跑时设置：

```bash
export MIR2EI_ROOT=/home/tetsuya/development/Mir3-Research   # 脚本根 (docs 等)
export MIR2EI_DATA=/home/tetsuya/development/Mir2ei-website/data
```

## 动态版 (可选)

`WikiServer.py` 是完整的动态百科服务（带搜索/筛选/版本对照），本地运行：

```bash
python3 scripts/WikiServer.py --port 8777
# 浏览器打开 http://127.0.0.1:8777
```

需要 `data/` 下的 JSON + `thumb/` 缩略图 + `img/` 图标。

## 数据来源

- **EI 传奇3.0 客户端** (`/home/tetsuya/NAS/TMP/EI传奇3.0客户端/`): 544 张地图、图库
- **Mud3 服务端** (`/home/tetsuya/NAS/TMP/Mud3/Envir/`): Mapinfo/Merchant/GuardList/刷怪配置
- **Zircon System.db**: 怪物/物品/技能/NPC/商店/掉落全表
- **老版 EI2.0 服务端三 DAT**: 老版怪物/装备/技能条目对照

## 维护

- 更新数据: 重跑 scripts/ 生成链路 → 重启 WikiServer → 重跑 static_site.py
- 推送到 GitHub 自动触发 Pages 更新 (CNAME 已绑定域名)
