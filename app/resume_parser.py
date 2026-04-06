# from PyPDF2 import PdfReader

# def extract_text_from_pdf(pdf_path: str) -> str:
#     try:
#         reader = PdfReader(pdf_path)
#     except Exception:
#         # Could be EmptyFileError or other read issues; return empty string
#         return ""

#     text_parts = []
#     for page in reader.pages:
#         try:
#             text = page.extract_text() or ""
#         except Exception:
#             text = ""
#         text_parts.append(text)
#     return "\n".join(text_parts)


# def extract_basic_resume_info(text: str) -> dict:
#     """Fallback lightweight parser to extract name, contact, skills, education using heuristics."""
#     import re
#     res = {"name": None, "contact": {}, "education": [], "skills": [], "experience_summary": None}
#     if not text:
#         return res
#     lines = [l.strip() for l in text.splitlines() if l.strip()]
#     # name: prefer a clean-looking line near the top that looks like a person name
#     def looks_like_name(s: str) -> bool:
#         s_clean = re.sub(r'[^A-Za-z \-.\'"]', '', s).strip()
#         if not s_clean:
#             return False
#         words = s_clean.split()
#         if len(words) < 2 or len(words) > 5:
#             return False
#         # avoid header-like lines
#         low = s.lower()
#         if any(k in low for k in ['resume', 'curriculum', 'contact', 'email', 'phone', 'linkedin', 'github', 'profile', 'summary']):
#             return False
#         # Prefer lines where words are Titlecase or ALL CAPS
#         cap_count = sum(1 for w in words if w[0].isupper() or w.isupper())
#         return cap_count >= len(words) - 1

#     name_candidate = None
#     for i, line in enumerate(lines[:10]):
#         if looks_like_name(line):
#             name_candidate = line
#             break
#     # fallback to first line if nothing better
#     if not name_candidate and lines:
#         name_candidate = lines[0]
#     res['name'] = name_candidate

#     # email
#     email_re = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
#     m = email_re.search(text)
#     if m:
#         res['contact']['email'] = m.group(0)

#     # phone
#     phone_re = re.compile(r"(\+?\d[\d \-().]{7,}\d)")
#     m2 = phone_re.search(text)
#     if m2:
#         res['contact']['phone'] = m2.group(0)

#     # linkedin / github: look for full URLs or simple "linkedin: name" patterns
#     linkedin_re = re.compile(r"(https?://)?(www\.)?linkedin\.com/[-A-Za-z0-9_/]+", re.I)
#     github_re = re.compile(r"(https?://)?(www\.)?github\.com/[-A-Za-z0-9_/]+", re.I)
#     mli = linkedin_re.search(text)
#     if mli:
#         val = mli.group(0)
#         if not val.startswith('http'):
#             val = 'https://' + val
#         res['contact']['linkedin'] = val
#     else:
#         # look for short forms like 'linkedin: name' in lines
#         for line in lines[:40]:
#             if 'linkedin' in line.lower():
#                 parts = line.split(':', 1)
#                 if len(parts) == 2 and parts[1].strip():
#                     handle = parts[1].strip()
#                     if not handle.startswith('http'):
#                         handle = 'https://www.linkedin.com/in/' + handle.split()[-1]
#                     res['contact']['linkedin'] = handle
#                     break

#     mgh = github_re.search(text)
#     if mgh:
#         val = mgh.group(0)
#         if not val.startswith('http'):
#             val = 'https://' + val
#         res['contact']['github'] = val
#     else:
#         for line in lines[:40]:
#             if 'github' in line.lower():
#                 parts = line.split(':', 1)
#                 if len(parts) == 2 and parts[1].strip():
#                     handle = parts[1].strip()
#                     if not handle.startswith('http'):
#                         handle = 'https://github.com/' + handle.split()[-1]
#                     res['contact']['github'] = handle
#                     break

#     # Try to infer name from email if the detected name looks like a header
#     if res.get('contact', {}).get('email') and (not res['name'] or len(res['name'].split()) == 1):
#         local = res['contact']['email'].split('@', 1)[0]
#         local = re.sub(r'[._\-]+', ' ', local)
#         inferred = ' '.join([w.capitalize() for w in local.split() if w])
#         if inferred and len(inferred.split()) >= 1:
#             # prefer inferred if current name is clearly not a proper name
#             if not res['name'] or any(k in res['name'].lower() for k in ['resume', 'curriculum']):
#                 res['name'] = inferred

#     # skills: look for 'SKILLS' section or common skill separators
#     skill_section = []
#     for i, line in enumerate(lines):
#         if 'skill' in line.lower():
#             # take next 1-3 lines as skills
#             skill_section = lines[i:i+4]
#             break
#     if skill_section:
#         skills = ", ".join(skill_section)
#         tokens = [s.strip() for s in re.split('[,;\n|•\-]', skills) if s.strip()]
#         res['skills'] = tokens
#     else:
#         # fallback: find comma-separated tech lists
#         techs = []
#         for line in lines[:20]:
#             if any(k in line.lower() for k in ['python','java','sql','react','node','tensorflow','pytorch','llm','huggingface']):
#                 techs.extend([t.strip() for t in re.split('[,;|]', line) if t.strip()])
#         res['skills'] = list(dict.fromkeys(techs))

#     # education: look for 'UNIVERSITY', 'B.Tech', 'Bachelor', 'College'
#     for line in lines:
#         if any(k in line.lower() for k in ['university','b.tech','bachelor','college','master','msc','mba']):
#             res['education'].append(line)

#     # experience summary: first paragraph after header 'PROFESSIONAL' or first 2-3 lines of experience
#     for i, line in enumerate(lines):
#         if 'professional' in line.lower() or 'experience' == line.lower():
#             snippet = lines[i+1:i+4]
#             res['experience_summary'] = ' '.join(snippet)
#             break

#     return res


# $$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$

"""
resume_parser.py — PDF text extraction and heuristic resume parsing.

Key fixes:
- Robust LinkedIn / GitHub extraction covering URLs, short handles, and inline text
- Phone regex covers Indian (+91) and international formats correctly
- Name detection avoids grabbing header words like 'Resume', 'CV', 'Profile'
- Skills section detection handles bullet-point and pipe-separated formats
- All extracted values are stripped and validated before storing
"""

from __future__ import annotations

import re
from typing import Dict, List, Any


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract raw text from a PDF file.

    Tries pdfplumber first (better layout), falls back to PyPDF2.
    Returns empty string on any failure.
    """
    # --- pdfplumber (preferred — handles columns and tables better) ----------
    try:
        import pdfplumber  # type: ignore
        with pdfplumber.open(pdf_path) as pdf:
            parts = []
            for page in pdf.pages:
                try:
                    t = page.extract_text() or ""
                except Exception:
                    t = ""
                parts.append(t)
        text = "\n".join(parts).strip()
        if text:
            return text
    except Exception:
        pass

    # --- PyPDF2 fallback -----------------------------------------------------
    try:
        from PyPDF2 import PdfReader  # type: ignore
        reader = PdfReader(pdf_path)
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                parts.append("")
        return "\n".join(parts).strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Heuristic parser
# ---------------------------------------------------------------------------

# Compiled patterns — compiled once at import time for performance
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I)

# Phone: matches +91-XXXXX-XXXXX, (0XX) XXXX XXXX, plain 10-digit, etc.
_PHONE_RE = re.compile(
    r"(?<!\d)"                          # not preceded by digit
    r"(\+?(?:91[\s\-]?)?"              # optional +91 country code
    r"(?:\(\d{2,4}\)[\s\-]?)?"         # optional area code in parens
    r"\d{3,5}[\s\-]?\d{3,5}[\s\-]?\d{3,5})"  # number body
    r"(?!\d)",                          # not followed by digit
    re.I
)

# LinkedIn: full URL or shorthand "linkedin: handle"
_LINKEDIN_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/([A-Za-z0-9\-_%]+)/?",
    re.I
)
_LINKEDIN_HANDLE_RE = re.compile(
    r"(?:linkedin|li)[:\s/]+([A-Za-z0-9\-_%]{3,50})",
    re.I
)

# GitHub: full URL or shorthand "github: handle"
_GITHUB_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9\-_%]+)/?",
    re.I
)
_GITHUB_HANDLE_RE = re.compile(
    r"(?:github|gh)[:\s/]+([A-Za-z0-9\-_%]{1,39})",
    re.I
)

# Words that disqualify a line from being a name
_NAME_BLACKLIST = re.compile(
    r"\b(resume|curriculum|vitae|cv|profile|summary|contact|email|phone|"
    r"linkedin|github|address|objective|skills|experience|education|"
    r"www\.|http|@)\b",
    re.I
)

# Noise phone numbers to reject (all same digit, too short after stripping spaces)
_PHONE_NOISE_RE = re.compile(r"^[\d\s\-().+]{4,6}$|^(\d)\1{6,}$")


def _clean_url(raw: str, prefix: str) -> str:
    """Ensure URL starts with https://."""
    raw = raw.strip().rstrip("/")
    if raw.startswith("http"):
        return raw
    return f"https://{prefix}{raw}"


def _extract_linkedin(text: str) -> str | None:
    """Return a normalised LinkedIn profile URL or None."""
    m = _LINKEDIN_URL_RE.search(text)
    if m:
        return f"https://www.linkedin.com/in/{m.group(1)}"

    # Shorthand in lines: "LinkedIn: ayush-shakya" or "linkedin/ayush-shakya"
    for line in text.splitlines()[:60]:
        if "linkedin" in line.lower():
            m2 = _LINKEDIN_HANDLE_RE.search(line)
            if m2:
                handle = m2.group(1).strip().strip("/")
                if 3 <= len(handle) <= 50 and "@" not in handle:
                    return f"https://www.linkedin.com/in/{handle}"
    return None


def _extract_github(text: str) -> str | None:
    """Return a normalised GitHub profile URL or None."""
    m = _GITHUB_URL_RE.search(text)
    if m:
        return f"https://github.com/{m.group(1)}"

    for line in text.splitlines()[:60]:
        if "github" in line.lower():
            m2 = _GITHUB_HANDLE_RE.search(line)
            if m2:
                handle = m2.group(1).strip().strip("/")
                if 1 <= len(handle) <= 39 and "@" not in handle:
                    return f"https://github.com/{handle}"
    return None


def _extract_phone(text: str) -> str | None:
    """Return the first plausible phone number from text."""
    for m in _PHONE_RE.finditer(text):
        raw = m.group(0).strip()
        digits_only = re.sub(r"\D", "", raw)
        # Must have 7-15 digits; reject noise like "2024" (year) or "123456"
        if 7 <= len(digits_only) <= 15 and not _PHONE_NOISE_RE.match(raw):
            return raw
    return None


def _looks_like_name(line: str) -> bool:
    """Heuristic: does this line look like a person's full name?"""
    clean = re.sub(r"[^A-Za-z .\-']", "", line).strip()
    if not clean:
        return False
    words = clean.split()
    # 2-5 words, each reasonably short
    if not (2 <= len(words) <= 5):
        return False
    if any(len(w) > 20 for w in words):
        return False
    if _NAME_BLACKLIST.search(line):
        return False
    # Most words should start with a capital letter
    cap = sum(1 for w in words if w and w[0].isupper())
    return cap >= max(1, len(words) - 1)


def _extract_name(lines: List[str], email: str | None) -> str | None:
    """Try to find the candidate's name from the top of the resume."""
    # First pass: look in first 10 lines for something name-shaped
    for line in lines[:10]:
        if _looks_like_name(line):
            return line.strip()

    # Second pass: infer from email local part (e.g. ayush.shakya → Ayush Shakya)
    if email:
        local = email.split("@")[0]
        local = re.sub(r"[\._\-\+0-9]+", " ", local).strip()
        words = [w.capitalize() for w in local.split() if len(w) > 1]
        if words:
            return " ".join(words)

    # Last resort: first non-empty line
    return lines[0].strip() if lines else None


def _extract_skills(lines: List[str], text: str) -> List[str]:
    """Extract skills from a Skills section or common technology keywords."""
    skills: List[str] = []

    # Find a Skills section header and grab the following lines
    for i, line in enumerate(lines):
        if re.match(r"^\s*(technical\s+)?skills?\s*[:\-]?\s*$", line, re.I):
            block_lines = lines[i + 1: i + 10]
            for bl in block_lines:
                # Stop if we hit another section header
                if re.match(r"^\s*[A-Z][A-Z\s]{3,}\s*$", bl):
                    break
                tokens = re.split(r"[,;|\n•·\-–]", bl)
                for t in tokens:
                    t = t.strip().strip("•·-– ")
                    if 1 < len(t) < 40:
                        skills.append(t)
            if skills:
                return list(dict.fromkeys(skills))  # dedupe, preserve order

    # Inline "Skills: Python, SQL, ..." on same line as header
    m = re.search(r"(?im)skills?\s*[:\-]\s*(.{5,})", text)
    if m:
        tokens = re.split(r"[,;|]", m.group(1))
        skills = [t.strip() for t in tokens if 1 < len(t.strip()) < 40]
        if skills:
            return list(dict.fromkeys(skills))

    # Fallback: scan for known technology keywords
    tech_pattern = re.compile(
        r"\b(Python|JavaScript|TypeScript|Java|C\+\+|C#|Go|Rust|SQL|NoSQL|"
        r"PostgreSQL|MySQL|MongoDB|Redis|AWS|GCP|Azure|Docker|Kubernetes|"
        r"TensorFlow|PyTorch|Keras|Scikit-learn|scikit.learn|Pandas|NumPy|"
        r"React|Node\.js|FastAPI|Flask|Django|LangChain|LLM|RAG|"
        r"Hugging\s*Face|OpenAI|Git|Linux|Spark|Hadoop|Tableau|Power\s*BI)\b",
        re.I,
    )
    found = tech_pattern.findall(text)
    return list(dict.fromkeys(t.strip() for t in found))


def _extract_education(lines: List[str]) -> List[str]:
    edu = []
    edu_keywords = re.compile(
        r"\b(university|college|institute|b\.?tech|m\.?tech|bachelor|master|"
        r"mba|msc|bsc|phd|degree|engineering|graduation)\b",
        re.I,
    )
    for line in lines:
        if edu_keywords.search(line) and len(line) > 5:
            edu.append(line.strip())
    return list(dict.fromkeys(edu))


def _extract_experience_summary(lines: List[str]) -> str | None:
    exp_header = re.compile(
        r"^\s*(work\s+)?experience|professional\s+experience|employment\s*$",
        re.I,
    )
    for i, line in enumerate(lines):
        if exp_header.match(line):
            snippet = [l for l in lines[i + 1: i + 5] if l.strip()]
            return " ".join(snippet) if snippet else None
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_basic_resume_info(text: str) -> Dict[str, Any]:
    """Parse raw resume text into a structured dict without an LLM.

    Returns keys: name, contact (email, phone, linkedin, github),
    education, skills, experience_summary, summary.
    """
    result: Dict[str, Any] = {
        "name": None,
        "contact": {},
        "education": [],
        "skills": [],
        "experience_summary": None,
        "summary": None,
    }

    if not text:
        return result

    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # ── Contact fields ────────────────────────────────────────────────────────
    email_m = _EMAIL_RE.search(text)
    email = email_m.group(0).lower() if email_m else None
    if email:
        result["contact"]["email"] = email

    phone = _extract_phone(text)
    if phone:
        result["contact"]["phone"] = phone

    linkedin = _extract_linkedin(text)
    if linkedin:
        result["contact"]["linkedin"] = linkedin

    github = _extract_github(text)
    if github:
        result["contact"]["github"] = github

    # ── Name ──────────────────────────────────────────────────────────────────
    result["name"] = _extract_name(lines, email)

    # ── Skills ───────────────────────────────────────────────────────────────
    result["skills"] = _extract_skills(lines, text)

    # ── Education ────────────────────────────────────────────────────────────
    result["education"] = _extract_education(lines)

    # ── Experience summary ───────────────────────────────────────────────────
    result["experience_summary"] = _extract_experience_summary(lines)

    return result