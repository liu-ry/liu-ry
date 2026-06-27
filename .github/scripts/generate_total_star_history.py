#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import os
import base64
import mimetypes
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Iterable


API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"
DEFAULT_USERNAME = "liu-ry"
DEFAULT_OUTPUT_SVG = Path("assets/github-stars-total.svg")
STAR_HISTORY_TEMPLATE_URL = "https://api.star-history.com/chart?repos=liu-ry%2FEmbodiedZero&type=date&legend=top-left"


@dataclass
class Repo:
    name: str
    full_name: str
    html_url: str
    description: str
    created_at: datetime
    stargazers_count: int
    fork: bool
    private: bool


def iso_to_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def request_json(url: str, token: str | None, accept: str) -> tuple[object, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": "liu-ry-star-history-generator",
            "X-GitHub-Api-Version": API_VERSION,
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            payload = response.read().decode("utf-8")
            headers = {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API request failed for {url}: {exc.code} {details}") from exc
    if not payload.strip():
        return [], headers
    return json.loads(payload), headers


def parse_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for item in link_header.split(","):
        parts = item.split(";")
        if len(parts) < 2:
            continue
        url = parts[0].strip().removeprefix("<").removesuffix(">")
        rel = parts[1].strip()
        if rel == 'rel="next"':
            return url
    return None


def paginate(url: str, token: str | None, accept: str) -> Iterable[object]:
    next_url = url
    while next_url:
        payload, headers = request_json(next_url, token=token, accept=accept)
        if not isinstance(payload, list):
            raise RuntimeError(f"Expected list payload from {next_url}, got {type(payload).__name__}")
        for item in payload:
            yield item
        next_url = parse_next_link(headers.get("link"))


def repo_from_payload(item: dict) -> Repo:
    return Repo(
        name=item["name"],
        full_name=item["full_name"],
        html_url=item["html_url"],
        description=item.get("description") or "",
        created_at=iso_to_datetime(item["created_at"]),
        stargazers_count=int(item.get("stargazers_count") or 0),
        fork=bool(item.get("fork")),
        private=bool(item.get("private")),
    )


def list_public_repos(username: str, token: str | None) -> list[Repo]:
    url = f"{API_ROOT}/users/{urllib.parse.quote(username)}/repos?type=owner&sort=created&direction=asc&per_page=100"
    repos: list[Repo] = []
    for item in paginate(url, token=token, accept="application/vnd.github+json"):
        if not isinstance(item, dict):
            continue
        repo = repo_from_payload(item)
        if not repo.private:
            repos.append(repo)
    return repos


def list_authenticated_repos(username: str, token: str) -> list[Repo]:
    url = f"{API_ROOT}/user/repos?visibility=all&affiliation=owner&sort=created&direction=asc&per_page=100"
    repos: list[Repo] = []
    for item in paginate(url, token=token, accept="application/vnd.github+json"):
        if not isinstance(item, dict):
            continue
        owner = item.get("owner") or {}
        if owner.get("login", "").lower() != username.lower():
            continue
        repos.append(repo_from_payload(item))
    return repos


def list_repos(username: str, token: str | None, include_forks: bool, include_private: bool) -> list[Repo]:
    repos_by_name = {repo.full_name: repo for repo in list_public_repos(username=username, token=token)}

    if include_private and token:
        try:
            for repo in list_authenticated_repos(username=username, token=token):
                repos_by_name[repo.full_name] = repo
        except RuntimeError as exc:
            print(
                f"warning: could not list authenticated/private repositories; "
                f"set STAR_HISTORY_TOKEN to a PAT with repo read access. {exc}",
                file=sys.stderr,
            )

    repos = list(repos_by_name.values())
    if not include_forks:
        repos = [repo for repo in repos if not repo.fork]
    return sorted(repos, key=lambda repo: repo.created_at)


def list_star_dates(repo: Repo, token: str | None) -> list[date]:
    owner, repo_name = repo.full_name.split("/", 1)
    url = f"{API_ROOT}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo_name)}/stargazers?per_page=100"
    star_dates: list[date] = []
    for item in paginate(url, token=token, accept="application/vnd.github.star+json"):
        if not isinstance(item, dict):
            continue
        starred_at = item.get("starred_at")
        if not starred_at:
            continue
        star_dates.append(iso_to_datetime(starred_at).date())
    return star_dates


def build_series(repos: list[Repo], token: str | None) -> tuple[list[tuple[date, int]], Counter[date]]:
    today = datetime.now(timezone.utc).date()
    daily_new_stars: Counter[date] = Counter()
    errors: list[str] = []
    for repo in repos:
        try:
            for star_day in list_star_dates(repo, token):
                daily_new_stars[star_day] += 1
        except RuntimeError as exc:
            visibility = "private" if repo.private else "public"
            errors.append(f"skipped {visibility} repo {repo.full_name}; could not read stargazers. {exc}")

    if errors:
        raise RuntimeError("Could not build complete star history:\n" + "\n".join(errors))

    start_day = min(daily_new_stars) - timedelta(days=1) if daily_new_stars else today - timedelta(days=29)

    series: list[tuple[date, int]] = []
    running_total = 0
    cursor = start_day
    while cursor <= today:
        running_total += daily_new_stars[cursor]
        series.append((cursor, running_total))
        cursor += timedelta(days=1)
    return series, daily_new_stars


def format_number(value: int) -> str:
    return f"{value:,}"


def compact_date(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def nice_top_tick(max_value: int) -> int:
    if max_value <= 5:
        return max(5, max_value)
    magnitude = 10 ** int(math.log10(max_value))
    normalized = max_value / magnitude
    if normalized <= 1:
        step = 1
    elif normalized <= 2:
        step = 2
    elif normalized <= 5:
        step = 5
    else:
        step = 10
    return int(math.ceil(max_value / (step * magnitude)) * step * magnitude)


def date_ticks(start_day: date, end_day: date, width: int) -> list[date]:
    total_days = max((end_day - start_day).days, 1)
    target_ticks = 6 if width >= 640 else 4
    if total_days <= target_ticks:
        return [start_day + timedelta(days=offset) for offset in range(total_days + 1)]

    raw_step = total_days / target_ticks
    candidates = [7, 14, 30, 60, 90, 120, 180, 365]
    step = next((value for value in candidates if value >= raw_step), candidates[-1])
    ticks = [start_day]
    cursor = start_day + timedelta(days=step)
    while cursor < end_day:
        ticks.append(cursor)
        cursor += timedelta(days=step)
    if ticks[-1] != end_day:
        ticks.append(end_day)
    return ticks


def tick_label(value: date, total_days: int) -> str:
    if total_days >= 365 * 2:
        return value.strftime("%Y")
    return value.strftime("%b %d")


def request_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "image/svg+xml,image/*,*/*",
            "User-Agent": "Mozilla/5.0 liu-ry-star-history-generator",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def data_uri_for_url(url: str, fallback_mime: str = "image/png") -> str:
    payload = request_bytes(url)
    mime = mimetypes.guess_type(urllib.parse.urlparse(url).path)[0] or fallback_mime
    return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"


def star_history_template_parts() -> tuple[str, str]:
    template = request_bytes(STAR_HISTORY_TEMPLATE_URL).decode("utf-8")
    defs_match = re.search(r"<defs><style>.*?</style></defs>", template)
    watermark_match = re.search(
        r'<image width="20" height="20" href="(data:image/png;base64,[^"]+)" transform="translate\(565 448\.333\)"/>',
        template,
    )
    if not defs_match or not watermark_match:
        raise RuntimeError("Could not extract Star History SVG template assets")
    return defs_match.group(0), watermark_match.group(1)


def github_avatar_data_uri(username: str) -> str:
    return data_uri_for_url(f"https://github.com/{urllib.parse.quote(username)}.png?size=44")


def svg_number(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text if text else "0"


def smooth_path(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    if len(points) == 1:
        x, y = points[0]
        return f"M{x:g} {y:g}"

    commands = [f"M{svg_number(points[0][0])} {svg_number(points[0][1])}"]
    previous = points[0]
    for current in points[1:]:
        x0, y0 = previous
        x1, y1 = current
        if abs(x1 - x0) < 0.001:
            commands.append(f"V{svg_number(y1)}")
        else:
            dx = x1 - x0
            c1x = x0 + dx * 0.5
            c2x = x1 - dx * 0.5
            commands.append(
                "C"
                f"{svg_number(c1x)} {svg_number(y0)} "
                f"{svg_number(c2x)} {svg_number(y1)} "
                f"{svg_number(x1)} {svg_number(y1)}"
            )
        previous = current
    return "".join(commands)


def render_svg(
    username: str,
    repos: list[Repo],
    series: list[tuple[date, int]],
    daily_new_stars: Counter[date],
    output_path: Path,
) -> None:
    width = 800
    height = 533.333
    plot_width = 700
    plot_height = 423.333

    start_day = series[0][0]
    end_day = series[-1][0]
    total_days = max((end_day - start_day).days, 1)
    max_total = max(total for _, total in series) if series else 0
    top_tick = nice_top_tick(max_total)
    y_tick_count = 5
    y_ticks = [round(top_tick * idx / y_tick_count) for idx in range(y_tick_count + 1)]

    def x_for(day: date) -> float:
        return ((day - start_day).days / total_days) * plot_width

    def y_for(total: int) -> float:
        if top_tick == 0:
            return plot_height
        return plot_height - (total / top_tick) * plot_height

    def build_star_history_points() -> list[tuple[float, float]]:
        points = [(x_for(start_day), y_for(0))]
        previous_total = 0
        for day, total in series:
            if total == previous_total:
                continue
            points.append((x_for(day), y_for(total)))
            previous_total = total
        if points[-1][0] != x_for(end_day):
            points.append((x_for(end_day), y_for(previous_total)))
        return points

    line_points = build_star_history_points()
    line_path = smooth_path(line_points)
    total_days_int = max((end_day - start_day).days, 1)
    tick_days: list[tuple[date, str]] = []
    previous_tick_text = None
    for tick_day in date_ticks(start_day, end_day, width):
        label = tick_label(tick_day, total_days_int)
        if label == previous_tick_text:
            continue
        previous_tick_text = label
        tick_days.append((tick_day, label))

    x_tick_markup: list[str] = []
    for tick_day, label in tick_days:
        x = x_for(tick_day)
        x_tick_markup.append(
            '<text y="6" fill="currentColor" class="tick" dy=".71em" '
            'style="font-family:xkcd;font-size:16px;fill:#000" '
            f'transform="translate({svg_number(x)} {svg_number(plot_height)})">'
            f"{label}</text>"
        )

    y_tick_markup: list[str] = []
    for y_tick in y_ticks:
        y = y_for(y_tick)
        label = " " if y_tick == 0 else format_number(y_tick)
        y_tick_markup.append(
            '<g class="tick">'
            f'<path stroke="currentColor" d="M0 {svg_number(y)}h-1"/>'
            f'<text x="-7" fill="currentColor" dy=".32em" '
            f'style="font-family:xkcd;font-size:16px;fill:#000" transform="translate(0 {svg_number(y)})">{label}</text>'
            "</g>"
        )

    daily_star_dots: list[str] = []
    previous_total = 0
    for day, total in series:
        gained = total - previous_total
        if gained > 0:
            daily_star_dots.append(
                f'<circle cx="{svg_number(x_for(day))}" cy="{svg_number(y_for(total))}" r="4.5" '
                f'fill="#dd4528" stroke="#fff" stroke-width="2"/>'
            )
        previous_total = total

    legend_label = f"{username}/all-repos"
    legend_width = max(171.5, len(legend_label) * 8.2 + 40)

    try:
        defs, watermark_href = star_history_template_parts()
    except Exception as exc:
        print(f"warning: using fallback Star History SVG assets. {exc}", file=sys.stderr)
        defs = (
            '<defs><style>@font-face{font-family:"xkcd";'
            'src:local("Comic Sans MS");}</style></defs>'
        )
        watermark_href = ""

    try:
        avatar_href = github_avatar_data_uri(username)
    except Exception as exc:
        print(f"warning: using plain title avatar fallback. {exc}", file=sys.stderr)
        avatar_href = ""

    watermark = (
        f'<image width="20" height="20" href="{watermark_href}" transform="translate(565 448.333)"/>'
        if watermark_href
        else ""
    )
    title_avatar = (
        f'<image width="22" height="22" x="316" y="12" clip-path="url(#clip-circle-title)" href="{avatar_href}"/>'
        if avatar_href
        else '<circle cx="327" cy="23" r="11" fill="#8b5a33"/>'
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" style="stroke-width:3;font-family:xkcd;background:#fff" role="img" aria-labelledby="title desc">
  <title id="title">{escape(username)} total GitHub star history</title>
  <desc id="desc">Cumulative star history across {len(repos)} repositories owned by {escape(username)}.</desc>
  {defs}
  <filter id="xkcdify" width="100%" height="100%" x="-5" y="-5" filterUnits="userSpaceOnUse"><feTurbulence baseFrequency=".05" result="noise" type="fractalNoise"/><feDisplacementMap in="SourceGraphic" in2="noise" scale="5" xChannelSelector="R" yChannelSelector="G"/></filter>
  <g pointer-events="all" transform="translate(70 60)">
    <text style="font-size:16px;fill:#666" text-anchor="middle" transform="translate(650 463.333)">star-history.com</text>
    {watermark}
    <g fill="none" class="xaxis" font-family="sans-serif" font-size="10" text-anchor="middle">
      <path stroke="currentColor" d="M.5.5h700" class="domain" filter="url(#xkcdify)" style="stroke:#000" transform="translate(0 {svg_number(plot_height)})"/>
      {''.join(x_tick_markup)}
    </g>
    <g fill="none" class="yaxis" font-family="sans-serif" font-size="10" text-anchor="end">
      <path stroke="currentColor" d="M-1 {svg_number(plot_height + 0.5)}H.5V.5H-1" class="domain" filter="url(#xkcdify)" style="stroke:#000"/>
      {''.join(y_tick_markup)}
    </g>
    <path fill="none" stroke="#dd4528" d="{line_path}" class="xkcd-chart-xyline" filter="url(#xkcdify)"/>
    {''.join(daily_star_dots)}
    <svg>
      <svg><rect width="{svg_number(legend_width)}" height="32" x="8" y="5" fill-opacity=".85" stroke="#000" stroke-width="2" filter="url(#xkcdify)" rx="5" ry="5" style="fill:#fff"/></svg>
      <svg><rect width="8" height="8" x="15" y="17" filter="url(#xkcdify)" rx="2" ry="2" style="fill:#dd4528"/><text x="29" y="25" style="font-size:15px;fill:#000">{escape(legend_label)}</text></svg>
    </svg>
  </g>
  <text x="50%" y="30" style="font-size:20px;font-weight:700;fill:#000" text-anchor="middle">Star History</text>
  <svg><defs><clipPath id="clip-circle-title"><circle cx="327" cy="23" r="11"/></clipPath></defs></svg>
  {title_avatar}
  <text x="50%" y="523.333" style="font-size:17px;fill:#000" text-anchor="middle">Date</text>
  <text x="-217" y="24" dy=".75em" style="font-size:17px;fill:#000" text-anchor="end" transform="rotate(-90)">GitHub Stars</text>
</svg>
"""
    output_path.write_text(svg, encoding="utf-8")


def main() -> int:
    username = os.environ.get("STAR_HISTORY_USERNAME", DEFAULT_USERNAME)
    output_svg = Path(os.environ.get("STAR_HISTORY_OUTPUT_SVG", DEFAULT_OUTPUT_SVG))
    include_forks = os.environ.get("STAR_HISTORY_INCLUDE_FORKS", "true").lower() in {"1", "true", "yes"}
    include_private = os.environ.get("STAR_HISTORY_INCLUDE_PRIVATE", "false").lower() in {"1", "true", "yes"}
    token = os.environ.get("STAR_HISTORY_TOKEN") or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    output_svg.parent.mkdir(parents=True, exist_ok=True)

    repos = list_repos(username=username, token=token, include_forks=include_forks, include_private=include_private)
    series, daily_new_stars = build_series(repos=repos, token=token)
    current_total_stars = sum(repo.stargazers_count for repo in repos)
    if series[-1][1] != current_total_stars:
        raise RuntimeError(
            f"Generated star history total ({series[-1][1]}) does not match "
            f"current repository star total ({current_total_stars})."
        )
    render_svg(
        username=username,
        repos=repos,
        series=series,
        daily_new_stars=daily_new_stars,
        output_path=output_svg,
    )

    print(
        json.dumps(
            {
                "username": username,
                "repo_count": len(repos),
                "private_repo_count": sum(1 for repo in repos if repo.private),
                "fork_repo_count": sum(1 for repo in repos if repo.fork),
                "latest_total_stars": series[-1][1],
                "current_total_stars": current_total_stars,
                "latest_day": compact_date(series[-1][0]),
                "output_svg": str(output_svg),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
