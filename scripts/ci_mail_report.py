#!/usr/bin/env python3
"""Generate a Jenkins build report mail body, subject and PNG trend chart.

Only the Python standard library is used.  The script is intentionally
defensive: Jenkins calls it from a ``post`` block and must never fail the
build because reporting data is missing or malformed.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import struct
import sys
import tempfile
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GATE_ORDER: list[tuple[str, str]] = [
    ("backend.setup", "后端依赖安装"),
    ("backend.ruff", "后端 ruff 静态检查"),
    ("backend.mypy", "后端 mypy 类型检查"),
    ("backend.migrations", "后端迁移一致性"),
    ("backend.pytest", "后端 pytest 用例"),
    ("frontend.setup", "前端依赖安装"),
    ("frontend.eslint", "前端 ESLint"),
    ("frontend.vuetsc", "前端 vue-tsc 类型检查"),
    ("frontend.vitest", "前端 Vitest 用例"),
    ("deploy", "部署与健康检查"),
]

GREEN = "#1b7f3b"
RED = "#c0392b"
ORANGE = "#b7791f"
GRAY = "#8c959f"
MUTED = "#57606a"
BORDER = "#d8dee4"
GRID = "#eaeef2"
SOFT_BG = "#f6f8fa"
TEXT = "#1f2328"

CST = timezone(timedelta(hours=8))
TREND_WIDTH = 760
TREND_HEIGHT = 260
TREND_IMAGE = "trend.png"

_HEX_COLOR = re.compile(r"^#([0-9a-fA-F]{6})$")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def esc(value: Any) -> str:
    """HTML-escape any value (attributes included)."""
    return html.escape("" if value is None else str(value), quote=True)


def rgb(color: str) -> tuple[int, int, int]:
    match = _HEX_COLOR.match(color)
    if not match:
        return (0, 0, 0)
    raw = match.group(1)
    return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def short_sha(sha: str, length: int = 7) -> str:
    sha = (sha or "").strip()
    return sha[:length] if sha else ""


def fmt_duration_ms(ms: Any) -> str:
    try:
        value = float(ms)
    except (TypeError, ValueError):
        return "—"
    if value < 0:
        return "—"
    if value < 1000:
        return f"{int(round(value))} 毫秒"
    seconds = value / 1000.0
    if seconds < 60:
        return f"{seconds:.1f} 秒"
    minutes = int(seconds // 60)
    rest = int(round(seconds - minutes * 60))
    if rest == 60:
        minutes += 1
        rest = 0
    return f"{minutes} 分 {rest} 秒"


def fmt_seconds(seconds: Any) -> str:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if value < 1:
        return f"{value:.2f} 秒"
    if value < 60:
        return f"{value:.1f} 秒"
    minutes = int(value // 60)
    return f"{minutes} 分 {int(round(value - minutes * 60))} 秒"


def fmt_percent(passed: int, total: int) -> str:
    if total <= 0:
        return "—"
    value = passed * 100.0 / total
    if abs(value - round(value)) < 0.05:
        return f"{int(round(value))}%"
    return f"{value:.1f}%"


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------


def parse_gate_file(path: Path) -> dict[str, Any] | None:
    """Read ``reports/gates/<key>.txt`` -> ``{"status", "ms"}``."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text:
        return None
    parts = [part.strip() for part in text.split("\t")]
    if len(parts) == 1:
        parts = text.split()
    if not parts:
        return None
    status = parts[0].upper()
    if status not in ("PASS", "FAIL"):
        return None
    ms: int | None = None
    if len(parts) > 1:
        try:
            ms = int(float(parts[1]))
        except (TypeError, ValueError):
            ms = None
    return {"status": status, "ms": ms}


def parse_gates(reports_dir: Path) -> dict[str, dict[str, Any]]:
    gates: dict[str, dict[str, Any]] = {}
    for key, _name in GATE_ORDER:
        data = parse_gate_file(reports_dir / "gates" / f"{key}.txt")
        if data is not None:
            gates[key] = data
    return gates


def _int_attr(element: ElementTree.Element, name: str) -> int | None:
    raw = element.get(name)
    if raw is None:
        return None
    return parse_int(raw, 0)


def _float_attr(element: ElementTree.Element, name: str) -> float | None:
    raw = element.get(name)
    if raw is None:
        return None
    return parse_float(raw, 0.0)


def _local_tag(element: ElementTree.Element, name: str) -> bool:
    return element.tag.rsplit("}", 1)[-1] == name


def _sum_child_suites(root: ElementTree.Element, attr: str) -> int | None:
    total = 0
    found = False
    for child in root:
        if _local_tag(child, "testsuite"):
            value = _int_attr(child, attr)
            if value is not None:
                total += value
                found = True
    return total if found else None


def _count_testcase_markers(testcases: list[ElementTree.Element], marker: str) -> int:
    return sum(1 for case in testcases if any(_local_tag(child, marker) for child in case))


def parse_junit(path: Path) -> dict[str, Any] | None:
    """Parse a JUnit XML root (``<testsuites>`` or ``<testsuite>``)."""
    if not path.is_file():
        return None
    try:
        root = ElementTree.parse(str(path)).getroot()
    except (OSError, ElementTree.ParseError):
        return None
    if root is None:
        return None

    root_is_suite = _local_tag(root, "testsuite")
    suites = [child for child in root if _local_tag(child, "testsuite")]
    testcases = [child for child in root if _local_tag(child, "testcase")]

    tests = _int_attr(root, "tests")
    if tests is None:
        tests = _sum_child_suites(root, "tests")
    if tests is None and root_is_suite:
        # Some reporters emit one <testsuite> root with <testcase> children.
        tests = len(testcases)
    if tests is None or tests <= 0:
        return None

    failures = _int_attr(root, "failures")
    if failures is None:
        aggregated = _sum_child_suites(root, "failures")
        failures = (
            aggregated
            if aggregated is not None
            else _count_testcase_markers(testcases, "failure")
        )

    errors = _int_attr(root, "errors")
    if errors is None:
        aggregated = _sum_child_suites(root, "errors")
        errors = (
            aggregated
            if aggregated is not None
            else _count_testcase_markers(testcases, "error")
        )

    skipped = _int_attr(root, "skipped")
    if skipped is None:
        # vitest does not always put ``skipped`` on the root; child suites do.
        aggregated = _sum_child_suites(root, "skipped")
        skipped = (
            aggregated
            if aggregated is not None
            else _count_testcase_markers(testcases, "skipped")
        )

    seconds = _float_attr(root, "time")
    if seconds is None:
        if suites:
            seconds = sum(_float_attr(child, "time") or 0.0 for child in suites)
        else:
            seconds = sum(_float_attr(case, "time") or 0.0 for case in testcases)

    failures = max(0, failures or 0)
    errors = max(0, errors or 0)
    skipped = max(0, skipped or 0)
    failed = failures + errors
    passed = max(0, tests - failed - skipped)
    return {
        "total": tests,
        "pass": passed,
        "fail": failed,
        "skip": skipped,
        "seconds": round(float(seconds or 0.0), 3),
    }


def parse_deploy_log(path: Path) -> dict[str, Any]:
    """Extract useful facts from the deploy stage log (if present)."""
    result: dict[str, Any] = {
        "exists": False,
        "commit": "",
        "images": {},
        "health_url": "",
        "health_attempts": "",
        "health_ok": False,
        "success": False,
        "failed": False,
    }
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result
    result["exists"] = True

    match = re.search(r"部署\s*commit\s*[:：]\s*([0-9a-fA-F]{7,64})", text)
    if match:
        result["commit"] = match.group(1)

    for service in ("my_blog_app_1", "my_blog_front_1"):
        match = re.search(
            r"镜像校验通过\s+" + re.escape(service) + r"\s*->\s*([0-9a-zA-Z]+)",
            text,
        )
        if match:
            result["images"][service] = match.group(1)

    match = re.search(r"健康检查通过\s*[:：]\s*(\S+)\s*\(([^)]*)\)", text)
    if match:
        result["health_ok"] = True
        result["health_url"] = match.group(1)
        result["health_attempts"] = match.group(2)
    elif "健康检查通过" in text:
        result["health_ok"] = True

    explicit_failure = "❌" in text or "部署失败" in text
    has_rollback = "回滚" in text
    result["success"] = "部署成功" in text and not explicit_failure
    # A bare "回滚" is only a failure signal when the deploy did not succeed
    # (scripts often mention "失败自动回滚" in their pre-deploy preamble).
    result["failed"] = explicit_failure or (has_rollback and not result["success"])
    return result


# ---------------------------------------------------------------------------
# History (JSONL)
# ---------------------------------------------------------------------------


def history_filename(job: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", (job or "my_blog").strip()) or "my_blog"
    return f"{safe}.jsonl"


def load_history(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    entries.append(item)
    except OSError:
        return []
    return entries


def write_history(path: Path, entries: list[dict[str, Any]]) -> None:
    """Atomically replace the JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def update_history(
    path: Path | None, entry: dict[str, Any], build_id: str
) -> tuple[list[dict[str, Any]], str | None]:
    """Append/replace current build, return (entries, previous result)."""
    if path is None:
        return [entry], None

    entries = load_history(path)
    if build_id:
        previous_entries = [
            item for item in entries if str(item.get("build", "")) != build_id
        ]
    else:
        previous_entries = list(entries)
    previous_result = None
    if previous_entries:
        raw = previous_entries[-1].get("result")
        if isinstance(raw, str) and raw.strip():
            previous_result = raw.strip().upper()

    entries = previous_entries + [entry]
    entries = entries[-50:]
    write_history(path, entries)
    return entries, previous_result


def entry_counts(entry: dict[str, Any]) -> tuple[int, int, int]:
    """Return (pass, fail, skip) for one history entry."""
    passed = failed = skipped = 0
    for key in ("pytest", "vitest"):
        data = entry.get(key)
        if isinstance(data, dict):
            passed += max(0, parse_int(data.get("pass"), 0))
            failed += max(0, parse_int(data.get("fail"), 0))
            skipped += max(0, parse_int(data.get("skip"), 0))
    return passed, failed, skipped


# ---------------------------------------------------------------------------
# Tiny 5x7 bitmap font + PNG canvas
# ---------------------------------------------------------------------------

FONT: dict[str, tuple[str, ...]] = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11111", "00010", "00100", "00010", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    "#": ("01010", "01010", "11111", "01010", "11111", "01010", "01010"),
    "%": ("11000", "11001", "00010", "00100", "01000", "10011", "00011"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    " ": ("00000",) * 7,
}


class Canvas:
    """Minimal RGB canvas with rectangle/text helpers."""

    def __init__(self, width: int, height: int, background: str = "#ffffff") -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray(bytes(rgb(background)) * (width * height))

    def rect(self, x: int, y: int, width: int, height: int, color: str) -> None:
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.width, x + width)
        y1 = min(self.height, y + height)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(rgb(color)) * (x1 - x0)
        for yy in range(y0, y1):
            start = (yy * self.width + x0) * 3
            self.pixels[start : start + len(row)] = row

    def hline(self, x: int, y: int, width: int, color: str) -> None:
        self.rect(x, y, width, 1, color)

    def vline(self, x: int, y: int, height: int, color: str) -> None:
        self.rect(x, y, 1, height, color)

    def png_bytes(self) -> bytes:
        raw = bytearray()
        stride = self.width * 3
        for row in range(self.height):
            raw.append(0)  # filter type: none
            raw.extend(self.pixels[row * stride : (row + 1) * stride])

        def chunk(kind: bytes, payload: bytes) -> bytes:
            crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
            return (
                struct.pack(">I", len(payload))
                + kind
                + payload
                + struct.pack(">I", crc)
            )

        header = struct.pack(
            ">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0
        )
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b"")
        )


def text_width(text: str, scale: int = 2) -> int:
    if not text:
        return 0
    return (len(text) * 6 - 1) * scale


def draw_text(
    canvas: Canvas, x: int, y: int, text: str, color: str, scale: int = 2
) -> int:
    cursor = x
    for char in text:
        glyph = FONT.get(char) or FONT.get(char.upper()) or FONT[" "]
        for row_index, row in enumerate(glyph):
            for col_index, bit in enumerate(row):
                if bit == "1":
                    canvas.rect(
                        cursor + col_index * scale,
                        y + row_index * scale,
                        scale,
                        scale,
                        color,
                    )
        cursor += 6 * scale
    return text_width(text, scale)


def nice_axis_max(value: int) -> int:
    """Round a max total up to a friendly number divisible by 4."""
    value = max(1, int(math.ceil(value)))
    if value <= 4:
        return 4
    target = value / 4.0
    exponent = math.floor(math.log10(target))
    magnitude = 10 ** exponent
    for multiplier in (1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        step = multiplier * magnitude
        if step != int(step):
            continue
        if step * 4 >= value:
            return int(step * 4)
    return int(math.ceil(value / 4.0) * 4)


def render_trend_png(entries: list[dict[str, Any]]) -> bytes:
    series = entries[-12:]
    counts = [entry_counts(entry) for entry in series]
    max_total = max((sum(item) for item in counts), default=1)
    axis_max = nice_axis_max(max_total)

    width, height = TREND_WIDTH, TREND_HEIGHT
    canvas = Canvas(width, height, "#ffffff")
    left, right = 48, width - 14
    top, bottom = 24, height - 30
    plot_height = bottom - top

    # Horizontal grid + Y labels (0/25/50/75/100% of axis max).
    for index in range(5):
        tick_value = int(round(axis_max * index / 4.0))
        y = bottom - int(round(plot_height * index / 4.0))
        canvas.hline(left, y, right - left, GRID)
        label = str(tick_value)
        label_x = left - 6 - text_width(label, 2)
        draw_text(canvas, max(0, label_x), y - 7, label, MUTED, 2)

    # Axes (light grey, matching the mail card).
    canvas.vline(left, top, plot_height + 1, "#d0d7de")
    canvas.hline(left, bottom, right - left, "#d0d7de")

    if counts:
        slot = (right - left) / float(len(counts))
        # Cap the width so 1-2 builds do not become one giant slab.
        bar_width = max(6, min(56, int(slot * 0.6)))
        scale = plot_height / float(axis_max)

        for index, (passed, failed, skipped) in enumerate(counts):
            center = left + slot * (index + 0.5)
            x = int(round(center - bar_width / 2.0))
            total = passed + failed + skipped

            pass_h = int(round(passed * scale))
            fail_h = int(round((passed + failed) * scale)) - pass_h
            skip_h = int(round(total * scale)) - pass_h - fail_h
            if passed > 0:
                pass_h = max(1, pass_h)
            if failed > 0:
                fail_h = max(1, fail_h)
            if skipped > 0:
                skip_h = max(1, skip_h)

            # Stack upwards from the bottom axis.
            y = bottom
            if pass_h > 0:
                canvas.rect(x, y - pass_h, bar_width, pass_h, GREEN)
                y -= pass_h
            if fail_h > 0:
                canvas.rect(x, y - fail_h, bar_width, fail_h, RED)
                y -= fail_h
            if skip_h > 0:
                canvas.rect(x, y - skip_h, bar_width, skip_h, "#d0d7de")

            build = str(series[index].get("build", "") or "")
            label = f"#{build}" if build else "#?"
            if len(label) > 5:
                label = label[-5:]
            label_x = int(round(center - text_width(label, 2) / 2.0))
            label_x = max(left, min(right - text_width(label, 2), label_x))
            draw_text(canvas, label_x, bottom + 8, label, MUTED, 2)

    return canvas.png_bytes()


# ---------------------------------------------------------------------------
# HTML mail rendering
# ---------------------------------------------------------------------------


def result_meta(result: str) -> tuple[str, str]:
    """Return (Chinese label, status colour)."""
    normalized = (result or "").strip().upper()
    if normalized == "SUCCESS":
        return "成功", GREEN
    if normalized == "ABORTED":
        return "已中止", ORANGE
    if normalized == "UNSTABLE":
        return "不稳定", ORANGE
    if normalized == "FAILURE":
        return "失败", RED
    if not normalized:
        return "未知", ORANGE
    return normalized, ORANGE


def deploy_status(gate: dict[str, Any] | None, log: dict[str, Any]) -> str:
    gate_status = (gate or {}).get("status")
    if gate_status == "FAIL" or log.get("failed"):
        return "失败"
    if gate_status == "PASS":
        return "成功"
    if log.get("success") or log.get("health_ok"):
        return "成功"
    return "未执行"


def deploy_color(status: str) -> str:
    if status == "成功":
        return GREEN
    if status == "失败":
        return RED
    return MUTED


def render_summary_cell(label: str, value: str, sub: str, color: str) -> str:
    sub_html = (
        f'<div style="font-size:11px;line-height:16px;color:{MUTED};">{esc(sub)}</div>'
        if sub
        else ""
    )
    return f"""<td width="25%" style="padding:0 4px;vertical-align:top;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;background:{SOFT_BG};border:1px solid #e5e7eb;">
    <tr><td align="center" style="padding:12px 6px;">
      <div style="font-size:12px;line-height:18px;color:{MUTED};">{esc(label)}</div>
      <div style="font-size:20px;line-height:28px;font-weight:700;color:{color};">{esc(value)}</div>
      {sub_html}
    </td></tr>
  </table>
</td>"""


def render_gate_rows(gates: dict[str, dict[str, Any]]) -> str:
    rows: list[str] = []
    for key, name in GATE_ORDER:
        data = gates.get(key)
        if data is None:
            status_html = f'<span style="color:{GRAY};">– 未执行</span>'
            duration = "—"
        elif data["status"] == "PASS":
            status_html = f'<span style="color:{GREEN};font-weight:600;">✓ 通过</span>'
            duration = fmt_duration_ms(data.get("ms"))
        else:
            status_html = f'<span style="color:{RED};font-weight:600;">✗ 失败</span>'
            duration = fmt_duration_ms(data.get("ms"))
        rows.append(
            f"""<tr>
  <td align="left" style="padding:7px 10px;border-bottom:1px solid {GRID};color:{TEXT};">{esc(name)}</td>
  <td align="left" style="padding:7px 10px;border-bottom:1px solid {GRID};">{status_html}</td>
  <td align="right" style="padding:7px 10px;border-bottom:1px solid {GRID};color:{MUTED};white-space:nowrap;">{esc(duration)}</td>
</tr>"""
        )
    return "".join(rows)


def render_test_rows(tests: list[tuple[str, dict[str, Any]]]) -> str:
    if not tests:
        return f"""<tr>
  <td colspan="7" align="center" style="padding:16px 10px;color:{MUTED};">无测试数据</td>
</tr>"""

    rows: list[str] = []
    for framework, data in tests:
        total = max(0, parse_int(data.get("total"), 0))
        passed = max(0, parse_int(data.get("pass"), 0))
        failed = max(0, parse_int(data.get("fail"), 0))
        skipped = max(0, parse_int(data.get("skip"), 0))
        rate = fmt_percent(passed, total)
        green_width = int(round(passed * 100.0 / total)) if total else 0
        green_width = min(100, max(0, green_width))
        grey_width = 100 - green_width

        rows.append(
            f"""<tr>
  <td align="left" style="padding:8px 10px;border-bottom:1px solid {GRID};font-weight:600;color:{TEXT};">{esc(framework)}</td>
  <td align="right" style="padding:8px 10px;border-bottom:1px solid {GRID};">{total}</td>
  <td align="right" style="padding:8px 10px;border-bottom:1px solid {GRID};color:{GREEN};font-weight:600;">{passed}</td>
  <td align="right" style="padding:8px 10px;border-bottom:1px solid {GRID};color:{RED if failed else MUTED};">{failed}</td>
  <td align="right" style="padding:8px 10px;border-bottom:1px solid {GRID};color:{MUTED};">{skipped}</td>
  <td align="right" style="padding:8px 10px;border-bottom:1px solid {GRID};color:{MUTED};white-space:nowrap;">{esc(fmt_seconds(data.get("seconds")))}</td>
  <td align="right" style="padding:8px 10px;border-bottom:1px solid {GRID};color:{TEXT};font-weight:600;white-space:nowrap;">{esc(rate)}</td>
</tr>
<tr>
  <td colspan="7" style="padding:0 10px 10px;border-bottom:1px solid {GRID};">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;table-layout:fixed;">
      <tr>
        <td width="{green_width}%" style="height:6px;background:{GREEN};font-size:0;line-height:0;">&nbsp;</td>
        <td width="{grey_width}%" style="height:6px;background:#eaeef2;font-size:0;line-height:0;">&nbsp;</td>
      </tr>
    </table>
  </td>
</tr>"""
        )
    return "".join(rows)


def render_html(data: dict[str, Any]) -> str:
    job = data["job"]
    build = data["build"]
    sha = data["sha"]
    short = data["short_sha"]
    result = data["result"]
    result_cn = data["result_cn"]
    status_color = data["status_color"]
    duration_text = data["duration_text"]
    gates = data["gates"]
    gate_passed = data["gate_passed"]
    gate_total = data["gate_total"]
    tests = data["tests"]
    test_total = data["test_total"]
    test_pass = data["test_pass"]
    test_pct = data["test_pct"]
    deploy = data["deploy"]
    deploy_state = data["deploy_state"]
    deploy_health = data["deploy_health"]
    health_color = data["health_color"]
    url = data["url"]
    entries = data["entries"]
    trend_exists = data["trend_exists"]

    latest_total = 0
    if entries:
        passed, failed, skipped = entry_counts(entries[-1])
        latest_total = passed + failed + skipped
    trend_count = len(entries[-12:]) if entries else 0

    gate_color = GREEN if gate_passed == gate_total else (RED if gate_passed < gate_total else MUTED)
    test_color = (
        GREEN
        if test_total and test_pass == test_total
        else (RED if test_total else MUTED)
    )

    summary = "".join(
        [
            render_summary_cell(
                "门禁通过",
                f"{gate_passed}/{gate_total}",
                "全部通过" if gate_passed == gate_total else "存在失败或未执行",
                gate_color,
            ),
            render_summary_cell(
                "用例通过率",
                f"{test_pass}/{test_total}" if test_total else "—",
                f"通过率 {test_pct}" if test_total else "无测试数据",
                test_color,
            ),
            render_summary_cell("构建耗时", duration_text, "", TEXT),
            render_summary_cell("部署状态", deploy_state, "", deploy_color(deploy_state)),
        ]
    )

    trend_section = ""
    if trend_exists and entries:
        trend_section = f"""<tr><td style="padding:24px 24px 10px;border-top:1px solid {GRID};">
  <div style="font-size:15px;line-height:22px;font-weight:700;color:{TEXT};">用例趋势</div>
</td></tr>
<tr><td style="padding:0 0 20px;">
  <img src="cid:trend.png" width="720" alt="最近构建用例趋势" style="display:block;width:720px;max-width:100%;height:auto;border:0;outline:none;text-decoration:none;">
  <div style="padding:8px 24px 0;font-size:12px;line-height:18px;color:{MUTED};">
    最近 {trend_count} 次构建；<span style="color:{GREEN};">绿色=通过</span>，<span style="color:{RED};">红色=失败</span>，<span style="color:{GRAY};">灰色=跳过</span>。<br>
    每条柱高对应该次构建的用例总数（通过 + 失败 + 跳过），最近一次 {latest_total} 个。
  </div>
</td></tr>"""

    images_html = []
    for service in ("my_blog_app_1", "my_blog_front_1"):
        image_id = deploy["images"].get(service, "")
        image_tag = service.replace("_1", "")
        extra = f"，镜像 {esc(image_id)}" if image_id else ""
        images_html.append(
            f'<div style="font-size:13px;line-height:20px;"><span style="font-family:Consolas,Menlo,monospace;">{esc(image_tag)}:{esc(short or "unknown")}</span><span style="color:{MUTED};">（容器 {esc(service)}{extra}）</span></div>'
        )
    image_rows = "".join(images_html)

    link_html = (
        f'<a href="{esc(url)}" style="color:#0969da;text-decoration:none;word-break:break-all;">{esc(url)}</a>'
        if url
        else "—"
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(job)} #{esc(build)} 构建报告</title>
</head>
<body style="margin:0;padding:0;background:#f5f7fa;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;background:#f5f7fa;">
<tr><td align="center" style="padding:16px 8px;">
<table role="presentation" width="720" cellpadding="0" cellspacing="0" border="0" style="width:720px;max-width:720px;border-collapse:collapse;background:#ffffff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,'PingFang SC','Microsoft YaHei',sans-serif;color:{TEXT};">
  <tr><td style="padding:0;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
      <tr><td style="background:{status_color};padding:20px 24px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
          <tr>
            <td align="left" style="font-size:20px;line-height:28px;font-weight:700;color:#ffffff;">{esc(job)} #{esc(build)}</td>
            <td align="right" style="font-size:14px;line-height:28px;font-weight:600;color:#ffffff;">{esc(result_cn)}</td>
          </tr>
          <tr>
            <td colspan="2" align="left" style="padding-top:8px;font-size:13px;line-height:20px;color:#ffffff;">提交 {esc(short or "未知")} · 构建耗时 {esc(duration_text)}</td>
          </tr>
        </table>
      </td></tr>
    </table>
  </td></tr>

  <tr><td style="padding:20px 20px 4px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
      <tr>{summary}</tr>
    </table>
  </td></tr>

  <tr><td style="padding:24px 24px 10px;border-top:1px solid {GRID};">
    <div style="font-size:15px;line-height:22px;font-weight:700;color:{TEXT};">门禁明细</div>
  </td></tr>
  <tr><td style="padding:0 24px 20px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-size:13px;line-height:20px;">
      <tr style="background:{SOFT_BG};">
        <th align="left" style="padding:8px 10px;border-bottom:1px solid {BORDER};color:{MUTED};font-weight:600;">检查项</th>
        <th align="left" style="padding:8px 10px;border-bottom:1px solid {BORDER};color:{MUTED};font-weight:600;">结果</th>
        <th align="right" style="padding:8px 10px;border-bottom:1px solid {BORDER};color:{MUTED};font-weight:600;">耗时</th>
      </tr>
      {render_gate_rows(gates)}
    </table>
  </td></tr>

  <tr><td style="padding:24px 24px 10px;border-top:1px solid {GRID};">
    <div style="font-size:15px;line-height:22px;font-weight:700;color:{TEXT};">用例统计</div>
  </td></tr>
  <tr><td style="padding:0 24px 20px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-size:13px;line-height:20px;">
      <tr style="background:{SOFT_BG};">
        <th align="left" style="padding:8px 10px;border-bottom:1px solid {BORDER};color:{MUTED};font-weight:600;">框架</th>
        <th align="right" style="padding:8px 10px;border-bottom:1px solid {BORDER};color:{MUTED};font-weight:600;">总数</th>
        <th align="right" style="padding:8px 10px;border-bottom:1px solid {BORDER};color:{MUTED};font-weight:600;">通过</th>
        <th align="right" style="padding:8px 10px;border-bottom:1px solid {BORDER};color:{MUTED};font-weight:600;">失败</th>
        <th align="right" style="padding:8px 10px;border-bottom:1px solid {BORDER};color:{MUTED};font-weight:600;">跳过</th>
        <th align="right" style="padding:8px 10px;border-bottom:1px solid {BORDER};color:{MUTED};font-weight:600;">耗时</th>
        <th align="right" style="padding:8px 10px;border-bottom:1px solid {BORDER};color:{MUTED};font-weight:600;">通过率</th>
      </tr>
      {render_test_rows(tests)}
    </table>
  </td></tr>

  {trend_section}

  <tr><td style="padding:24px 24px 10px;border-top:1px solid {GRID};">
    <div style="font-size:15px;line-height:22px;font-weight:700;color:{TEXT};">构建与部署</div>
  </td></tr>
  <tr><td style="padding:0 24px 20px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-size:13px;line-height:20px;">
      <tr>
        <td width="130" align="left" style="padding:7px 0;color:{MUTED};vertical-align:top;white-space:nowrap;">Commit</td>
        <td align="left" style="padding:7px 0;font-family:Consolas,Menlo,monospace;word-break:break-all;">{esc(sha or "未知")}</td>
      </tr>
      <tr>
        <td align="left" style="padding:7px 0;color:{MUTED};vertical-align:top;white-space:nowrap;">镜像 tag</td>
        <td align="left" style="padding:7px 0;">{image_rows}</td>
      </tr>
      <tr>
        <td align="left" style="padding:7px 0;color:{MUTED};vertical-align:top;white-space:nowrap;">健康检查</td>
        <td align="left" style="padding:7px 0;color:{health_color};">{esc(deploy_health)}</td>
      </tr>
      <tr>
        <td align="left" style="padding:7px 0;color:{MUTED};vertical-align:top;white-space:nowrap;">部署状态</td>
        <td align="left" style="padding:7px 0;color:{deploy_color(deploy_state)};font-weight:600;">{esc(deploy_state)}</td>
      </tr>
      <tr>
        <td align="left" style="padding:7px 0;color:{MUTED};vertical-align:top;white-space:nowrap;">构建链接</td>
        <td align="left" style="padding:7px 0;">{link_html}</td>
      </tr>
    </table>
  </td></tr>

  <tr><td style="background:{SOFT_BG};padding:16px 24px;border-top:1px solid {GRID};">
    <div style="font-size:12px;line-height:18px;color:{MUTED};">
      本邮件由 Jenkins 自动生成。
    </div>
    <div style="padding-top:4px;font-size:12px;line-height:18px;color:{MUTED};">
      结果：{esc(result_cn)} · 提交 {esc(short or "未知")} · 生成时间 {esc(data["generated_at"])}
    </div>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def render_fallback_html(workspace: Path, args: argparse.Namespace, error: str) -> None:
    """Best-effort minimal mail body when something unexpected happened."""
    reports_dir = workspace / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    job = getattr(args, "job", "") or "my_blog"
    build = getattr(args, "build", "") or "?"
    result = (getattr(args, "result", "") or "").upper()
    label, color = result_meta(result)
    url = getattr(args, "url", "") or ""
    link = (
        f'<a href="{esc(url)}" style="color:#0969da;">{esc(url)}</a>'
        if url
        else "—"
    )
    body = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>{esc(job)} #{esc(build)}</title></head>
<body style="margin:0;padding:0;background:#f5f7fa;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f7fa;">
<tr><td align="center" style="padding:16px 8px;">
<table role="presentation" width="720" cellpadding="0" cellspacing="0" border="0" style="width:720px;max-width:720px;background:#ffffff;border-collapse:collapse;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,'PingFang SC','Microsoft YaHei',sans-serif;color:{TEXT};">
<tr><td style="background:{color};padding:20px 24px;color:#ffffff;">
  <div style="font-size:20px;font-weight:700;">{esc(job)} #{esc(build)} · {esc(label)}</div>
</td></tr>
<tr><td style="padding:24px;">
  <p style="margin:0 0 12px;font-size:14px;line-height:22px;">报告数据生成失败，以下是兜底信息。</p>
  <p style="margin:0 0 12px;font-size:13px;line-height:20px;color:{MUTED};">原因：{esc(error)}</p>
  <p style="margin:0;font-size:13px;line-height:20px;">构建链接：{link}</p>
</td></tr>
</table>
</td></tr></table>
</body></html>"""
    (reports_dir / "email.html").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------


def build_subject(
    *,
    job: str,
    build: str,
    result: str,
    gate_passed: int,
    gate_total: int,
    test_total: int,
    test_pass: int,
    test_fail: int,
    previous_result: str | None,
) -> str:
    normalized = (result or "").strip().upper()
    is_success = normalized == "SUCCESS"
    if is_success:
        tag = "恢复" if previous_result and previous_result != "SUCCESS" else "部署成功"
    else:
        tag = "失败"

    base = f"[Jenkins][{tag}] {job} #{build}"
    gate_part = f"门禁 {gate_passed}/{gate_total}"

    test_part = ""
    if test_total > 0:
        if is_success:
            test_part = f"用例 {test_pass}/{test_total} 通过"
        else:
            test_part = f"用例 {test_fail}/{test_total} 失败"

    subject = f"{base} · {gate_part}"
    if test_part:
        subject = f"{base} · {gate_part}，{test_part}"

    if len(subject) <= 78:
        return subject

    # Drop the test detail first.
    subject = f"{base} · {gate_part}"
    if len(subject) <= 78:
        return subject

    # Last resort: keep the important suffix and truncate the job name.
    suffix = f" · {gate_part}"
    room = max(8, 78 - len("[Jenkins][") - len(tag) - len("] ") - len(f" #{build}") - len(suffix))
    short_job = job if len(job) <= room else job[: max(1, room - 1)] + "…"
    subject = f"[Jenkins][{tag}] {short_job} #{build}{suffix}"
    return subject[:78]


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成 Jenkins 构建邮件正文、主题和趋势图（仅标准库）。"
    )
    parser.add_argument("--workspace", default=".", help="项目根目录，默认当前目录")
    parser.add_argument("--history-dir", default="", help="趋势历史目录，可空")
    parser.add_argument("--job", default="my_blog", help="任务名")
    parser.add_argument("--build", default="", help="构建号")
    parser.add_argument("--sha", default="", help="提交 SHA")
    parser.add_argument("--result", default="SUCCESS", help="构建结果")
    parser.add_argument("--duration-ms", default="0", help="构建耗时（毫秒）")
    parser.add_argument("--url", default="", help="构建页面链接")
    parser.add_argument("--deploy-log", default="reports/deploy.log", help="部署日志路径")
    args, _unknown = parser.parse_known_args(argv)
    return args


def run(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace or ".").expanduser().resolve()
    reports_dir = workspace / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    job = (args.job or "my_blog").strip()
    build = str(args.build or "").strip()
    result = (args.result or "").strip().upper() or "UNKNOWN"
    duration_ms = parse_int(args.duration_ms, 0)
    url = (args.url or "").strip()

    deploy_log_path = Path(args.deploy_log or "reports/deploy.log")
    if not deploy_log_path.is_absolute():
        deploy_log_path = workspace / deploy_log_path

    gates = parse_gates(reports_dir)
    pytest_data = parse_junit(reports_dir / "pytest.xml")
    vitest_data = parse_junit(reports_dir / "vitest.xml")
    deploy_log = parse_deploy_log(deploy_log_path)

    sha = (args.sha or "").strip() or deploy_log.get("commit", "")
    short = short_sha(sha)

    gate_passed = sum(1 for data in gates.values() if data.get("status") == "PASS")
    gate_total = len(GATE_ORDER)

    tests: list[tuple[str, dict[str, Any]]] = []
    if pytest_data is not None:
        tests.append(("pytest", pytest_data))
    if vitest_data is not None:
        tests.append(("Vitest", vitest_data))

    test_total = sum(parse_int(data.get("total"), 0) for _name, data in tests)
    test_pass = sum(parse_int(data.get("pass"), 0) for _name, data in tests)
    test_fail = sum(parse_int(data.get("fail"), 0) for _name, data in tests)
    test_skip = sum(parse_int(data.get("skip"), 0) for _name, data in tests)
    test_pct = fmt_percent(test_pass, test_total)

    log_gate = gates.get("deploy")
    deploy_state = deploy_status(log_gate, deploy_log)

    if deploy_log.get("health_ok"):
        health = "通过"
        if deploy_log.get("health_url"):
            health += f" · {deploy_log['health_url']}"
        if deploy_log.get("health_attempts"):
            health += f" （{deploy_log['health_attempts']}）"
    elif deploy_state == "成功":
        health = "通过"
    elif deploy_state == "失败":
        health = "失败"
    else:
        health = "未执行"

    health_color = GREEN if deploy_log.get("health_ok") else (RED if health == "失败" else MUTED)

    generated_at = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    entry: dict[str, Any] = {
        "ts": datetime.now(CST).isoformat(timespec="seconds"),
        "build": build,
        "result": result,
        "sha": short,
        "durationMs": duration_ms,
        "gates": {key: data["status"] for key, data in gates.items()},
    }
    if pytest_data is not None:
        entry["pytest"] = dict(pytest_data)
    if vitest_data is not None:
        entry["vitest"] = dict(vitest_data)

    history_path: Path | None = None
    if args.history_dir:
        history_path = Path(args.history_dir).expanduser() / history_filename(job)

    warnings: list[str] = []
    previous_result: str | None = None
    entries: list[dict[str, Any]] = [entry]
    if history_path is not None:
        try:
            entries, previous_result = update_history(history_path, entry, build)
        except Exception as exc:  # history must never break reporting
            warnings.append(f"历史写入失败：{exc}")
            try:
                entries = load_history(history_path) + [entry]
            except Exception:
                entries = [entry]

    trend_path = reports_dir / TREND_IMAGE
    trend_written = False
    try:
        # No history store configured -> no history file -> no trend image.
        if entries and history_path is not None:
            trend_path.write_bytes(render_trend_png(entries))
            trend_written = trend_path.is_file()
        else:
            # Drop a stale chart from an earlier invocation.
            try:
                trend_path.unlink(missing_ok=True)
            except OSError:
                pass
    except Exception as exc:
        warnings.append(f"趋势图生成失败：{exc}")
        trend_written = False

    result_cn, status_color = result_meta(result)
    data: dict[str, Any] = {
        "job": job,
        "build": build or "?",
        "sha": sha,
        "short_sha": short,
        "result": result,
        "result_cn": result_cn,
        "status_color": status_color,
        "duration_ms": duration_ms,
        "duration_text": fmt_duration_ms(duration_ms),
        "gates": gates,
        "gate_passed": gate_passed,
        "gate_total": gate_total,
        "tests": tests,
        "test_total": test_total,
        "test_pass": test_pass,
        "test_fail": test_fail,
        "test_skip": test_skip,
        "test_pct": test_pct,
        "deploy": deploy_log,
        "deploy_state": deploy_state,
        "deploy_health": health,
        "health_color": health_color,
        "url": url,
        "entries": entries,
        "trend_exists": trend_written,
        "generated_at": generated_at,
    }

    try:
        html_text = render_html(data)
        (reports_dir / "email.html").write_text(html_text, encoding="utf-8")
    except Exception as exc:
        warnings.append(f"邮件正文渲染失败：{exc}")
        render_fallback_html(workspace, args, str(exc))

    subject = build_subject(
        job=job,
        build=build or "?",
        result=result,
        gate_passed=gate_passed,
        gate_total=gate_total,
        test_total=test_total,
        test_pass=test_pass,
        test_fail=test_fail,
        previous_result=previous_result,
    )
    try:
        (reports_dir / "email-subject.txt").write_text(subject + "\n", encoding="utf-8")
    except Exception as exc:
        warnings.append(f"邮件主题写入失败：{exc}")

    for warning in warnings:
        print(f"[ci_mail_report] 警告: {warning}", file=sys.stdout)

    trend_count = len(entries[-12:]) if trend_written else 0
    outputs = [str(reports_dir / "email.html"), str(reports_dir / "email-subject.txt")]
    if trend_written:
        outputs.append(str(trend_path))
    print(
        f"[ci_mail_report] 门禁 {gate_passed}/{gate_total} · 用例 {test_total} · "
        f"趋势 {trend_count} 条 · {' , '.join(outputs)}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args: argparse.Namespace | None = None
    try:
        args = parse_args(argv)
        return run(args)
    except SystemExit as exc:  # argparse errors must not fail the build either
        if not exc.code:
            return 0
        print(f"[ci_mail_report] 警告: 参数解析失败（退出码 {exc.code}）", file=sys.stdout)
        try:
            fallback_args = parse_args([])
            workspace = Path(fallback_args.workspace or ".").expanduser().resolve()
            render_fallback_html(workspace, fallback_args, f"参数解析失败：{exc}")
        except Exception:
            pass
        return 0
    except Exception as exc:  # never fail the Jenkins build
        print(f"[ci_mail_report] 警告: 报告生成失败：{exc}", file=sys.stdout)
        try:
            workspace = Path(getattr(args, "workspace", ".") or ".").expanduser().resolve()
            fallback_args = args or parse_args([])
            render_fallback_html(workspace, fallback_args, str(exc))
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
