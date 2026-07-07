from __future__ import annotations

import html
from pathlib import Path
from typing import Any


def _change_kind(entry: dict) -> str:
    old, new = entry.get("old"), entry.get("new")
    if old and new:
        return "changed"
    if new and not old:
        return "added"
    return "removed"


def _fmt_entry(entry: dict | None) -> str:
    if not entry:
        return "—"
    size = entry.get("size")
    size_s = f"{size:,}" if isinstance(size, int) else str(size)
    return f"{entry.get('hash', '')} · {size_s} B"


def render_diff_html(diff: dict[str, Any]) -> str:
    meta = diff["meta"]
    summary = diff["summary"]
    changes: dict[str, dict] = diff["changes"]

    grouped: dict[str, list[tuple[str, dict]]] = {
        "changed": [],
        "added": [],
        "removed": [],
    }
    with_types: list[tuple[str, dict]] = []

    for path, entry in changes.items():
        kind = _change_kind(entry)
        grouped[kind].append((path, entry))
        if entry.get("affected_type_ids"):
            with_types.append((path, entry))

    for items in grouped.values():
        items.sort(key=lambda x: x[0])
    with_types.sort(key=lambda x: x[0])

    def render_items(items: list[tuple[str, dict]], default_open: bool = False) -> str:
        parts: list[str] = []
        for path, entry in items:
            kind = _change_kind(entry)
            affected = entry.get("affected_type_ids") or []
            open_attr = " open" if default_open and len(items) <= 5 else ""
            types_html = ""
            if affected:
                chips = []
                for t in affected:
                    label = f"{t['typeID']}"
                    if t.get("name_zh"):
                        label += f" {t['name_zh']}"
                    elif t.get("name_en"):
                        label += f" {t['name_en']}"
                    chips.append(f'<span class="chip">{html.escape(label)}</span>')
                types_html = f'<div class="types">{"".join(chips)}</div>'

            parts.append(f"""
<details class="item item-{kind}"{open_attr}>
  <summary>
    <span class="badge badge-{kind}">{kind}</span>
    <code class="path">{html.escape(path)}</code>
  </summary>
  <div class="body">
    <div class="hash-row"><span class="label">旧</span><code>{html.escape(_fmt_entry(entry.get("old")))}</code></div>
    <div class="hash-row"><span class="label">新</span><code>{html.escape(_fmt_entry(entry.get("new")))}</code></div>
    {types_html}
  </div>
</details>""")
        return "\n".join(parts) if parts else '<p class="empty">无</p>'

    old_v = meta["old_version"]
    new_v = meta["new_version"]
    generated = html.escape(meta.get("generated_at", ""))

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EVE 资源比对 {old_v} → {new_v}</title>
<style>
  :root {{
    --bg: #0f1419;
    --surface: #1a2332;
    --border: #2d3a4f;
    --text: #e6edf3;
    --muted: #8b9cb3;
    --accent: #58a6ff;
    --changed: #d29922;
    --added: #3fb950;
    --removed: #f85149;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "Segoe UI", system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
    padding: 1.5rem;
    max-width: 960px;
    margin-inline: auto;
  }}
  h1 {{ font-size: 1.35rem; font-weight: 600; margin: 0 0 .25rem; }}
  .meta {{ color: var(--muted); font-size: .875rem; margin-bottom: 1.25rem; }}
  .stats {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: .75rem;
    margin-bottom: 1.5rem;
  }}
  .stat {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: .75rem 1rem;
  }}
  .stat b {{ display: block; font-size: 1.5rem; font-weight: 600; }}
  .stat span {{ font-size: .8rem; color: var(--muted); }}
  .toolbar {{
    display: flex;
    gap: .5rem;
    flex-wrap: wrap;
    margin-bottom: 1rem;
  }}
  .toolbar input {{
    flex: 1;
    min-width: 200px;
    padding: .5rem .75rem;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
  }}
  .toolbar button {{
    padding: .5rem .85rem;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    cursor: pointer;
  }}
  .toolbar button:hover {{ border-color: var(--accent); }}
  section {{ margin-bottom: 1.5rem; }}
  section > h2 {{
    font-size: 1rem;
    margin: 0 0 .75rem;
    color: var(--muted);
    font-weight: 500;
  }}
  details.item {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    margin-bottom: .4rem;
  }}
  details.item[hidden] {{ display: none; }}
  summary {{
    cursor: pointer;
    padding: .55rem .75rem;
    list-style: none;
    display: flex;
    align-items: flex-start;
    gap: .5rem;
  }}
  summary::-webkit-details-marker {{ display: none; }}
  .badge {{
    font-size: .7rem;
    text-transform: uppercase;
    padding: .15rem .4rem;
    border-radius: 4px;
    flex-shrink: 0;
    font-weight: 600;
  }}
  .badge-changed {{ background: color-mix(in srgb, var(--changed) 25%, transparent); color: var(--changed); }}
  .badge-added {{ background: color-mix(in srgb, var(--added) 25%, transparent); color: var(--added); }}
  .badge-removed {{ background: color-mix(in srgb, var(--removed) 25%, transparent); color: var(--removed); }}
  .path {{
    font-size: .78rem;
    word-break: break-all;
    color: var(--text);
  }}
  .body {{ padding: 0 .75rem .65rem 1rem; border-top: 1px solid var(--border); }}
  .hash-row {{ font-size: .75rem; margin-top: .4rem; }}
  .hash-row .label {{ color: var(--muted); display: inline-block; width: 1.5rem; }}
  .hash-row code {{ word-break: break-all; color: var(--muted); }}
  .types {{ display: flex; flex-wrap: wrap; gap: .35rem; margin-top: .5rem; }}
  .chip {{
    font-size: .75rem;
    background: color-mix(in srgb, var(--accent) 15%, transparent);
    color: var(--accent);
    padding: .2rem .5rem;
    border-radius: 4px;
  }}
  .empty {{ color: var(--muted); font-size: .875rem; }}
  .collapse-all {{ margin-left: auto; }}
</style>
</head>
<body>
  <h1>EVE 资源比对</h1>
  <p class="meta">
    {old_v} → {new_v} · SDE {meta.get("sde_build", "")} · {generated}
  </p>

  <div class="stats">
    <div class="stat"><b>{summary["changed"]}</b><span>哈希变更</span></div>
    <div class="stat"><b>{summary["added"]}</b><span>新增</span></div>
    <div class="stat"><b>{summary["removed"]}</b><span>移除</span></div>
    <div class="stat"><b>{summary["affected_types"]}</b><span>受影响物品</span></div>
  </div>

  <div class="toolbar">
    <input type="search" id="q" placeholder="筛选路径…" autocomplete="off">
    <button type="button" data-filter="all">全部</button>
    <button type="button" data-filter="changed">变更</button>
    <button type="button" data-filter="added">新增</button>
    <button type="button" data-filter="removed">移除</button>
    <button type="button" data-filter="affected">有影响物品</button>
    <button type="button" class="collapse-all" id="collapse">全部折叠</button>
  </div>

  <section id="sec-affected">
    <h2>有影响物品的路径 ({len(with_types)})</h2>
    {render_items(with_types)}
  </section>

  <section id="sec-changed">
    <h2>哈希变更 ({len(grouped["changed"])})</h2>
    {render_items(grouped["changed"])}
  </section>

  <section id="sec-added">
    <h2>新增 ({len(grouped["added"])})</h2>
    {render_items(grouped["added"])}
  </section>

  <section id="sec-removed">
    <h2>移除 ({len(grouped["removed"])})</h2>
    {render_items(grouped["removed"])}
  </section>

<script>
(function() {{
  const q = document.getElementById("q");
  const items = () => document.querySelectorAll("details.item");
  const sections = document.querySelectorAll("section");

  function applyFilter() {{
    const text = q.value.trim().toLowerCase();
    const active = document.querySelector(".toolbar button.active");
    const mode = active ? active.dataset.filter : "all";

    items().forEach(el => {{
      const path = el.querySelector(".path").textContent.toLowerCase();
      const kind = el.classList.contains("item-changed") ? "changed"
        : el.classList.contains("item-added") ? "added" : "removed";
      const hasTypes = !!el.querySelector(".types");
      let show = !text || path.includes(text);
      if (mode === "changed") show = show && kind === "changed";
      if (mode === "added") show = show && kind === "added";
      if (mode === "removed") show = show && kind === "removed";
      if (mode === "affected") show = show && hasTypes;
      el.hidden = !show;
    }});

    sections.forEach(sec => {{
      const visible = sec.querySelectorAll("details.item:not([hidden])").length;
      sec.hidden = visible === 0;
    }});
  }}

  document.querySelectorAll(".toolbar button[data-filter]").forEach(btn => {{
    btn.addEventListener("click", () => {{
      document.querySelectorAll(".toolbar button[data-filter]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      applyFilter();
    }});
  }});
  document.querySelector('.toolbar button[data-filter="all"]').classList.add("active");
  q.addEventListener("input", applyFilter);

  document.getElementById("collapse").addEventListener("click", () => {{
    items().forEach(el => {{ el.open = false; }});
  }});
}})();
</script>
</body>
</html>"""


def write_diff_html(diff: dict[str, Any], path: Path) -> None:
    path.write_text(render_diff_html(diff), encoding="utf-8")
