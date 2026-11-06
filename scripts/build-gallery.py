#!/usr/bin/env python3
"""Copy captured PNGs into a portable, interactive, server-free screenshot gallery."""

import html
import json
import shutil
import struct
import zipfile
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
captures = json.loads((repo / ".validation/captures.json").read_text())
root = repo / "docs/screenshots"
root.mkdir(parents=True, exist_ok=True)
manifest = []
for item in captures:
    filename = item["name"] + ".png"
    target = root / filename
    shutil.copyfile(item["path"], target)
    with target.open("rb") as f:
        header = f.read(24)
        width, height = struct.unpack(">II", header[16:24])
    manifest.append(
        {"name": item["name"], "label": item["label"], "image": filename, "width": width, "height": height}
    )
(root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
initial = next(m for m in manifest if m["name"] == "08-mod-library")
buttons = "".join(
    f'<button class="thumb" type="button" data-label="{html.escape(m["label"], quote=True)}" aria-pressed="false"><img src="{m["image"]}" alt="{html.escape(m["label"], quote=True)}" loading="eager"><span>{html.escape(m["label"])}</span></button>'
    for m in manifest
)
page = (
    """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GameHub screenshots</title>
<style>
*{box-sizing:border-box}body{margin:0;font:14px/1.5 var(--font-sans,system-ui);color:var(--foreground,#edf1f7)}p{color:var(--muted-foreground,#7b8494);margin:0 0 12px}.viewer{background:var(--card,#161e2a);border:1px solid var(--border,#283343);border-radius:var(--radius,12px);padding:16px;margin-bottom:16px}.heading{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px}.heading strong{font-size:15px}.heading button,.heading a{background:var(--secondary,#233043);color:var(--secondary-foreground,#edf1f7);border:1px solid var(--border,#364357);border-radius:6px;padding:6px 10px;font:inherit;text-decoration:none;cursor:pointer}.stage{max-height:850px;overflow:auto;display:flex;justify-content:center}.stage img{display:block;width:100%;height:auto;max-height:740px;object-fit:contain}.stage.zoom img{max-height:none;align-self:start}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.thumb{border:1px solid var(--border,#283343);border-radius:8px;padding:6px;background:var(--card,#161e2a);color:var(--foreground,#edf1f7);text-align:left;cursor:pointer;min-width:0}.thumb[aria-pressed=true]{outline:2px solid var(--primary,#a9ecc6);outline-offset:1px}.thumb img{display:block;width:100%;height:90px;object-fit:contain;background:var(--code-background,#0c1017);border-radius:4px}.thumb span{display:block;padding:6px 2px 0;font-size:11px}button:focus-visible,a:focus-visible{outline:3px solid var(--ring,#85b9ff);outline-offset:3px}@media(max-width:500px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.thumb img{height:95px}.stage img{max-height:650px}}
</style></head><body><p>16 screenshots from the running local application. Select any thumbnail. Sample mods are labelled demo fixtures.</p><section class="viewer"><div class="heading"><strong id="caption">INITIAL_LABEL</strong><span><button id="zoom" type="button">Zoom / fit</button> <a id="download" download href="INITIAL_IMAGE">PNG ↓</a></span></div><div class="stage" id="stage"><img id="large" src="INITIAL_IMAGE" alt="INITIAL_LABEL"></div></section><div class="grid">BUTTONS</div><script>
const large=document.getElementById('large'),caption=document.getElementById('caption'),download=document.getElementById('download');download.href=large.src;for(const button of document.querySelectorAll('.thumb')){button.addEventListener('click',()=>{for(const b of document.querySelectorAll('.thumb'))b.setAttribute('aria-pressed',String(b===button));large.src=button.querySelector('img').src;large.alt=button.dataset.label;caption.textContent=button.dataset.label;download.href=large.src;document.getElementById('stage').scrollTop=0;});if(button.dataset.label===caption.textContent)button.setAttribute('aria-pressed','true');}document.getElementById('zoom').onclick=()=>document.getElementById('stage').classList.toggle('zoom');
</script></body></html>""".replace("INITIAL_LABEL", html.escape(initial["label"], quote=True))
    .replace("INITIAL_IMAGE", initial["image"])
    .replace("BUTTONS", buttons)
)
(root / "index.html").write_text(page)
with zipfile.ZipFile(
    repo / ".validation/gamehub-screenshots.zip", "w", compression=zipfile.ZIP_DEFLATED
) as archive:
    for path in sorted(root.iterdir()):
        archive.write(path, arcname="gamehub-screenshots/" + path.name)
print(f"Created {len(manifest)} screenshots, portable HTML gallery and ZIP.")
