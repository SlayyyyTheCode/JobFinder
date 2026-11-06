"""ATS-readable document rendering. Employer/title/date/education text is copied from the ledger,
never from model output."""
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..models import CandidateFact
from ..tailoring.qa import parse_ym
from ..tailoring.schema import TailoredResume, TailorOptions

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
TEMPLATES = Path(__file__).parent / "templates"


def fmt_date(s: str, style: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if s.lower() in ("present", "current", "now"):
        return "Present"
    has_month = bool(re.match(r"^\d{4}[-/]\d{1,2}", s))
    ym = parse_ym(s)
    if not ym:
        return s
    y, m = ym
    if style == "YYYY" or not has_month:
        return str(y)
    if style == "MM/YYYY":
        return f"{m:02d}/{y}"
    return f"{MONTHS[m - 1]} {y}"


def _id(x: str) -> int | None:
    m = re.match(r"^\s*F?(\d+)", str(x))
    return int(m.group(1)) if m else None


def build_view(t: TailoredResume, facts: dict[int, CandidateFact], opt: TailorOptions) -> dict:
    contact = next((f.data for f in facts.values() if f.type == "contact"), {})
    line = [contact.get(k) for k in ("location", "phone", "email") if contact.get(k)] + list(contact.get("links") or [])
    exp = []
    for r in t.roles:
        f = facts.get(_id(r.fact_id))
        if not f or f.type != "employment":
            continue
        d = f.data
        dates = " – ".join(x for x in [fmt_date(d.get("start", ""), opt.date_format),
                                       fmt_date(d.get("end", ""), opt.date_format)] if x)
        exp.append({"title": d.get("title", ""), "employer": d.get("employer", ""), "location": d.get("location", ""),
                    "dates": dates, "bullets": [b.text.strip() for b in r.bullets if b.text.strip()]})
    if opt.ordering == "preserve":
        order = {f.id: f.sort_order for f in facts.values()}
        exp_ids = [_id(r.fact_id) for r in t.roles]
        exp = [e for _, e in sorted(zip(exp_ids, exp), key=lambda p: order.get(p[0], 0))]
    projects = []
    if opt.include_projects:
        for p in t.projects:
            f = facts.get(_id(p.fact_id))
            if f and f.type == "project" and f.id not in opt.exclude_project_ids:
                projects.append({"name": f.text, "bullets": [b.text for b in p.bullets]})
    skills, seen = [], set()
    for sk in t.skills:
        f = facts.get(_id(sk.fact_id))
        name = f.text if f and f.type == "skill" else None
        if name and name.lower() not in seen:
            seen.add(name.lower())
            skills.append(name)
    edu = []
    for i in t.education_fact_ids:
        f = facts.get(_id(i))
        if f and f.type == "education":
            d = f.data
            edu.append({"line": f.text, "dates": " – ".join(x for x in [fmt_date(d.get("start", ""), opt.date_format),
                                                                         fmt_date(d.get("end", ""), opt.date_format)] if x),
                        "grade": d.get("grade", "")})
    certs = [facts[_id(i)].text for i in t.certification_fact_ids if _id(i) in facts]
    langs = [f.text for f in facts.values() if f.type == "language"]
    return {"name": contact.get("name", ""), "contact_line": " | ".join(line), "summary": t.summary,
            "experience": exp, "projects": projects, "skills": skills, "education": edu,
            "certifications": certs, "languages": langs}


def to_text(v: dict) -> str:
    out = [v["name"], v["contact_line"], ""]
    if v["summary"]:
        out += ["SUMMARY", v["summary"], ""]
    if v["experience"]:
        out.append("EXPERIENCE")
        for e in v["experience"]:
            out.append(f"{e['title']} — {e['employer']}  {e['dates']}")
            out += [f"• {b}" for b in e["bullets"]]
            out.append("")
    if v["projects"]:
        out.append("PROJECTS")
        for p in v["projects"]:
            out.append(p["name"])
            out += [f"• {b}" for b in p["bullets"]]
        out.append("")
    if v["skills"]:
        out += ["SKILLS", ", ".join(v["skills"]), ""]
    if v["education"]:
        out.append("EDUCATION")
        out += [f"{e['line']}  {e['dates']}" for e in v["education"]]
        out.append("")
    if v["certifications"]:
        out += ["CERTIFICATIONS"] + v["certifications"]
    return "\n".join(out).strip()


def render_docx(v: dict, path: Path) -> None:
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, Cm

    d = docx.Document()
    for sec in d.sections:
        sec.top_margin = sec.bottom_margin = Cm(1.6)
        sec.left_margin = sec.right_margin = Cm(1.8)
    st = d.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(10.5)
    st.paragraph_format.space_after = Pt(2)

    def heading(text):
        p = d.add_paragraph()
        p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(10), Pt(3)
        r = p.add_run(text.upper())
        r.bold, r.font.size = True, Pt(11)
        pPr = p._p.get_or_add_pPr()
        bdr = OxmlElement("w:pBdr")
        b = OxmlElement("w:bottom")
        for k, val in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", "444444")):
            b.set(qn(k), val)
        bdr.append(b)
        pPr.append(bdr)

    def bullet(text):
        p = d.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(1)
        p.add_run(text)

    p = d.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(v["name"])
    r.bold, r.font.size = True, Pt(18)
    if v["contact_line"]:
        p = d.add_paragraph(v["contact_line"])
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if v["summary"]:
        heading("Summary")
        d.add_paragraph(v["summary"])
    if v["experience"]:
        heading("Experience")
        for e in v["experience"]:
            p = d.add_paragraph()
            p.paragraph_format.space_before = Pt(5)
            r = p.add_run(e["title"])
            r.bold = True
            p.add_run(f" — {e['employer']}")
            if e["location"]:
                p.add_run(f", {e['location']}")
            if e["dates"]:
                p.add_run(f"\t{e['dates']}")
                p.paragraph_format.tab_stops.add_tab_stop(Cm(17.4), alignment=2)
            for b in e["bullets"]:
                bullet(b)
    if v["projects"]:
        heading("Projects")
        for pr in v["projects"]:
            p = d.add_paragraph()
            p.add_run(pr["name"]).bold = True
            for b in pr["bullets"]:
                bullet(b)
    if v["skills"]:
        heading("Skills")
        d.add_paragraph(", ".join(v["skills"]))
    if v["education"]:
        heading("Education")
        for e in v["education"]:
            p = d.add_paragraph(e["line"])
            if e["dates"]:
                p.add_run(f"\t{e['dates']}")
                p.paragraph_format.tab_stops.add_tab_stop(Cm(17.4), alignment=2)
            if e["grade"]:
                d.add_paragraph(e["grade"])
    if v["certifications"]:
        heading("Certifications")
        for c in v["certifications"]:
            bullet(c)
    if v["languages"]:
        heading("Languages")
        d.add_paragraph(", ".join(v["languages"]))
    d.core_properties.author = v["name"]
    d.core_properties.title = f"{v['name']} — Resume"
    d.save(str(path))


_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))


def html_for(v: dict, template: str = "classic") -> str:
    name = template if (TEMPLATES / f"{template}.html").exists() else "classic"
    return _env.get_template(f"{name}.html").render(**v)


def html_to_pdf(html: str, path: Path) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.set_content(html, wait_until="load")
        page.pdf(path=str(path), format="A4", print_background=True,
                 margin={"top": "14mm", "bottom": "14mm", "left": "15mm", "right": "15mm"})
        b.close()


def render_pdf(v: dict, path: Path, template: str = "classic") -> None:
    html_to_pdf(html_for(v, template), path)


def pdf_check(path: Path, v: dict) -> tuple[int, list[str]]:
    """Re-parse generated PDF like an ATS would. Returns (page_count, missing_strings)."""
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        pages = len(pdf.pages)
        text = "\n".join(pg.extract_text() or "" for pg in pdf.pages)
    flat = re.sub(r"\s+", " ", text).lower()
    must = [v["name"]] + [e["employer"] for e in v["experience"]] + [e["title"] for e in v["experience"]]
    missing = [m for m in must if m and re.sub(r"\s+", " ", m).lower() not in flat]
    return pages, missing


def render_letter(name: str, contact_line: str, body: str, docx_path: Path) -> None:
    import docx
    from docx.shared import Pt
    d = docx.Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(11)
    d.add_paragraph().add_run(name).bold = True
    if contact_line:
        d.add_paragraph(contact_line)
    d.add_paragraph("")
    for para in body.split("\n\n"):
        d.add_paragraph(para.strip())
    d.save(str(docx_path))
