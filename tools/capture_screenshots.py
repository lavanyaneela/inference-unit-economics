"""Captures framed screenshots of the two reports the tool actually produces.

Three rules, each inherited from a failure on an earlier repository. Frame by
heading, not by pixel offset, and fail when a named heading no longer exists,
because that means the report changed shape and the shot would be meaningless.
Pass `full_page=True` even with a clip, or Chromium clamps the clip to the
viewport. And read back the computed style of the verdict badge, failing if it
is invisible, because a specificity collision can render a verdict green on
green and the screenshot tool is the only thing in the pipeline that can see
pixels.

The reports are built, not photographed from disk: a screenshot of a stale
report is worse than no screenshot. There are two because the output has two
shapes, decided and refused, and one file name for both meant the documented
regeneration step could silently replace one shape with the other.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "evidence"

#: name -> (extra CLI args, first h1/h2 text to frame from, heading to stop
#: before, or None for the end of the document)
SHOTS: dict[str, tuple[list[str], str, str | None]] = {
    "report-decided": ([], "inference-unit-economics report",
                       "Where the cheap choice changes"),
    "report-refused": (["--max-band-pct", "10"],
                       "inference-unit-economics report",
                       "What the Terraform cannot represent"),
}


def build_report(args: list[str], path: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "inference_unit_economics.cli", "report",
         "--out", str(path), *args],
        cwd=ROOT, check=True,
    )
    if not path.exists():
        raise SystemExit("the report was not written, so there is nothing to photograph")


def capture() -> dict:
    from playwright.sync_api import sync_playwright

    manifest: dict = {"shots": []}
    with sync_playwright() as play:
        browser = play.chromium.launch()
        page = browser.new_page(viewport={"width": 1100, "height": 900},
                                device_scale_factor=2)
        for name, (args, start, stop) in SHOTS.items():
            report = OUT / f"{name}.html"
            build_report(args, report)
            page.goto(report.resolve().as_uri())
            page.wait_for_timeout(200)
            frame = page.evaluate(
                """([start, stop]) => {
                    const heads = [...document.querySelectorAll('h1, h2')];
                    const a = heads.find(h => h.textContent.trim() === start);
                    if (!a) return {error: 'missing heading: ' + start};
                    let bottom = document.body.scrollHeight;
                    if (stop) {
                        const b = heads.find(h => h.textContent.trim() === stop);
                        if (!b) return {error: 'missing heading: ' + stop};
                        bottom = b.getBoundingClientRect().top + window.scrollY;
                    }
                    const top = a.getBoundingClientRect().top + window.scrollY;
                    return {top: Math.max(0, top - 12), bottom};
                }""",
                [start, stop],
            )
            if "error" in frame:
                raise SystemExit(
                    f"{name}: {frame['error']}. The report changed shape; refusing "
                    "to photograph the wrong section."
                )
            badge = page.evaluate(
                """() => {
                    const badge = document.querySelector('.badge');
                    if (!badge) return null;
                    const style = getComputedStyle(badge);
                    return {text: badge.textContent, colour: style.color,
                            background: style.backgroundColor,
                            visible: badge.offsetWidth > 0 && badge.offsetHeight > 0};
                }"""
            )
            if badge is None or not badge["visible"]:
                raise SystemExit(f"{name}: the verdict badge is missing or invisible")
            if badge["colour"] == badge["background"]:
                raise SystemExit(
                    f"{name}: the verdict badge renders {badge['colour']} on itself"
                )
            target = OUT / f"{name}.png"
            page.screenshot(
                path=str(target), full_page=True,
                clip={"x": 0, "y": frame["top"], "width": 1100,
                      "height": max(120, frame["bottom"] - frame["top"])},
            )
            manifest["shots"].append({
                "file": target.name, "report": report.name,
                "framed_from": start, "framed_to": stop,
                "badge": badge,
            })
            print(f"wrote {target.name}: badge {badge['text']!r} "
                  f"{badge['colour']} on {badge['background']}")
        browser.close()
    (OUT / "screenshot-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    capture()
