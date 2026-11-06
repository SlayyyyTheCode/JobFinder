"""File validation + raw text extraction (spec §5.2 steps 1-2)."""
import hashlib
import io
import logging
import os
import re
import subprocess
import zipfile
from pathlib import Path

log = logging.getLogger("jobpilot.ingest")
MAX_BYTES = 10 * 1024 * 1024
DEFENDER = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Windows Defender" / "MpCmdRun.exe"


class IngestError(ValueError):
    pass


def detect_format(filename: str, data: bytes) -> str:
    if len(data) == 0:
        raise IngestError("File is empty.")
    if len(data) > MAX_BYTES:
        raise IngestError("File is larger than 10 MB.")
    ext = Path(filename).suffix.lower()
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
                if "word/document.xml" in names:
                    if any(n.startswith("word/vbaProject") for n in names):
                        raise IngestError("Macro-enabled Word documents are not accepted.")
                    return "docx"
        except zipfile.BadZipFile:
            pass
    if ext == ".doc" or data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "doc"
    raise IngestError("Unsupported file. Upload a PDF, DOCX or DOC resume.")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def malware_scan(path: Path) -> None:
    """Best-effort scan with Windows Defender when it is the active AV.
    MpCmdRun uses exit code 2 both for 'threat found' and for generic failures (e.g. another AV is
    active), so the decision is made on its output text."""
    if not DEFENDER.exists():
        return
    try:
        r = subprocess.run([str(DEFENDER), "-Scan", "-ScanType", "3", "-File", str(path), "-DisableRemediation"],
                           capture_output=True, timeout=120, text=True, errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"found (\d+) threats?", out, re.I)
    if m and int(m.group(1)) > 0:
        raise IngestError("File was flagged by Windows Defender and was rejected.")
    if r.returncode != 0 and not re.search(r"found no threats", out, re.I):
        log.warning("Defender scan unavailable (exit %s): %s", r.returncode, out.strip()[:200])


def convert_doc_to_docx(src: Path) -> Path:
    """Legacy .doc → .docx via installed Microsoft Word (COM through PowerShell)."""
    dst = src.with_suffix(".converted.docx")
    ps = (
        "$w = New-Object -ComObject Word.Application; $w.Visible = $false; "
        f"$d = $w.Documents.Open('{src}', $false, $true); "
        f"$d.SaveAs2('{dst}', 16); $d.Close($false); $w.Quit()"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=120, check=True)
    except (OSError, subprocess.SubprocessError) as e:
        raise IngestError("Could not convert .doc (Microsoft Word not available). Save it as DOCX or PDF and re-upload.") from e
    if not dst.exists():
        raise IngestError("Could not convert .doc. Save it as DOCX or PDF and re-upload.")
    return dst


def pdf_text(data: bytes) -> str:
    import pdfplumber
    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text(x_tolerance=1.5, y_tolerance=3) or "")
    return "\n\n".join(out).strip()


def docx_text(data: bytes) -> str:
    import docx
    d = docx.Document(io.BytesIO(data))
    lines: list[str] = []
    body = d.element.body
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            t = "".join(n.text or "" for n in child.iter() if n.tag.endswith("}t")).strip()
            if t:
                lines.append(t)
        elif tag == "tbl":
            for row in child.iter():
                if row.tag.endswith("}tr"):
                    cells = []
                    for tc in row.iter():
                        if tc.tag.endswith("}tc"):
                            cells.append("".join(n.text or "" for n in tc.iter() if n.tag.endswith("}t")).strip())
                    if any(cells):
                        lines.append(" | ".join(c for c in cells if c))
    for section in d.sections:  # contact details often live in headers
        for p in section.header.paragraphs:
            if p.text.strip():
                lines.insert(0, p.text.strip())
    return "\n".join(lines).strip()


def needs_ocr(text: str) -> bool:
    return len(text.replace(" ", "")) < 200
