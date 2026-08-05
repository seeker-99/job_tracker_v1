"""Generates HTML and Markdown reports from a list of DiffItem."""
from pathlib import Path
from datetime import datetime
from jinja2 import Template

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

HTML_TEMPLATE = Template("""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Job Tracker Report - {{ date }}</title>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 900px; margin: 40px auto; color: #1a1a1a; }
  h1 { font-size: 22px; }
  .summary { color: #555; margin-bottom: 24px; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 32px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #eee; font-size: 14px; }
  th { background: #fafafa; }
  .NEW { color: #0a7a0a; font-weight: 600; }
  .UPDATED { color: #b8860b; font-weight: 600; }
  .REMOVED { color: #b00020; font-weight: 600; }
  a { color: #2563eb; text-decoration: none; }
  a:hover { text-decoration: underline; }
</style>
</head>
<body>
  <h1>Job Tracker Report</h1>
  <div class="summary">{{ date }} &middot; {{ new_count }} new &middot; {{ updated_count }} updated &middot; {{ removed_count }} removed</div>

  {% if items %}
  <table>
    <tr><th>Status</th><th>Company</th><th>Title</th><th>Location</th><th>Experience</th><th>Posted</th><th>Link</th></tr>
    {% for i in items %}
    <tr>
      <td class="{{ i.status }}">{{ i.status }}</td>
      <td>{{ i.company }}</td>
      <td>{{ i.title }}</td>
      <td>{{ i.location or "—" }}</td>
      <td>{{ i.experience or "—" }}</td>
      <td>{{ i.posted_date or "—" }}</td>
      <td><a href="{{ i.link }}" target="_blank">View</a></td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p>No new relevant openings today.</p>
  {% endif %}

  {% if failed_sites %}
  <h2>Sites that failed this run</h2>
  <ul>
    {% for s in failed_sites %}<li>{{ s }}</li>{% endfor %}
  </ul>
  {% endif %}
</body>
</html>
""")


def generate_html(items, failed_sites, date_str) -> str:
    new_count = sum(1 for i in items if i.status == "NEW")
    updated_count = sum(1 for i in items if i.status == "UPDATED")
    removed_count = sum(1 for i in items if i.status == "REMOVED")
    html = HTML_TEMPLATE.render(
        date=date_str, items=items, failed_sites=failed_sites,
        new_count=new_count, updated_count=updated_count, removed_count=removed_count,
    )
    out_path = REPORTS_DIR / f"report_{date_str}.html"
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)


def generate_markdown(items, failed_sites, date_str) -> str:
    lines = [f"# Job Tracker Report — {date_str}", ""]
    new_count = sum(1 for i in items if i.status == "NEW")
    updated_count = sum(1 for i in items if i.status == "UPDATED")
    removed_count = sum(1 for i in items if i.status == "REMOVED")
    lines.append(f"**{new_count} new, {updated_count} updated, {removed_count} removed**")
    lines.append("")

    if items:
        lines.append("| Status | Company | Title | Location | Experience | Posted | Link |")
        lines.append("|---|---|---|---|---|---|---|")
        for i in items:
            lines.append(
                f"| {i.status} | {i.company} | {i.title} | {i.location or '—'} | "
                f"{i.experience or '—'} | {i.posted_date or '—'} | [Apply]({i.link}) |"
            )
    else:
        lines.append("No new relevant openings today.")

    if failed_sites:
        lines.append("")
        lines.append("## Sites that failed this run")
        for s in failed_sites:
            lines.append(f"- {s}")

    md = "\n".join(lines)
    out_path = REPORTS_DIR / f"report_{date_str}.md"
    out_path.write_text(md, encoding="utf-8")
    return str(out_path)
