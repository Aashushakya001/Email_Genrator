from PyPDF2 import PdfReader

def extract_text_from_pdf(pdf_path: str) -> str:
    try:
        reader = PdfReader(pdf_path)
    except Exception:
        # Could be EmptyFileError or other read issues; return empty string
        return ""

    text_parts = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text_parts.append(text)
    return "\n".join(text_parts)


def extract_basic_resume_info(text: str) -> dict:
    """Fallback lightweight parser to extract name, contact, skills, education using heuristics."""
    import re
    res = {"name": None, "contact": {}, "education": [], "skills": [], "experience_summary": None}
    if not text:
        return res
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # name: prefer a clean-looking line near the top that looks like a person name
    def looks_like_name(s: str) -> bool:
        s_clean = re.sub(r'[^A-Za-z \-.\'"]', '', s).strip()
        if not s_clean:
            return False
        words = s_clean.split()
        if len(words) < 2 or len(words) > 5:
            return False
        # avoid header-like lines
        low = s.lower()
        if any(k in low for k in ['resume', 'curriculum', 'contact', 'email', 'phone', 'linkedin', 'github', 'profile', 'summary']):
            return False
        # Prefer lines where words are Titlecase or ALL CAPS
        cap_count = sum(1 for w in words if w[0].isupper() or w.isupper())
        return cap_count >= len(words) - 1

    name_candidate = None
    for i, line in enumerate(lines[:10]):
        if looks_like_name(line):
            name_candidate = line
            break
    # fallback to first line if nothing better
    if not name_candidate and lines:
        name_candidate = lines[0]
    res['name'] = name_candidate

    # email
    email_re = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    m = email_re.search(text)
    if m:
        res['contact']['email'] = m.group(0)

    # phone
    phone_re = re.compile(r"(\+?\d[\d \-().]{7,}\d)")
    m2 = phone_re.search(text)
    if m2:
        res['contact']['phone'] = m2.group(0)

    # linkedin / github: look for full URLs or simple "linkedin: name" patterns
    linkedin_re = re.compile(r"(https?://)?(www\.)?linkedin\.com/[-A-Za-z0-9_/]+", re.I)
    github_re = re.compile(r"(https?://)?(www\.)?github\.com/[-A-Za-z0-9_/]+", re.I)
    mli = linkedin_re.search(text)
    if mli:
        val = mli.group(0)
        if not val.startswith('http'):
            val = 'https://' + val
        res['contact']['linkedin'] = val
    else:
        # look for short forms like 'linkedin: name' in lines
        for line in lines[:40]:
            if 'linkedin' in line.lower():
                parts = line.split(':', 1)
                if len(parts) == 2 and parts[1].strip():
                    handle = parts[1].strip()
                    if not handle.startswith('http'):
                        handle = 'https://www.linkedin.com/in/' + handle.split()[-1]
                    res['contact']['linkedin'] = handle
                    break

    mgh = github_re.search(text)
    if mgh:
        val = mgh.group(0)
        if not val.startswith('http'):
            val = 'https://' + val
        res['contact']['github'] = val
    else:
        for line in lines[:40]:
            if 'github' in line.lower():
                parts = line.split(':', 1)
                if len(parts) == 2 and parts[1].strip():
                    handle = parts[1].strip()
                    if not handle.startswith('http'):
                        handle = 'https://github.com/' + handle.split()[-1]
                    res['contact']['github'] = handle
                    break

    # Try to infer name from email if the detected name looks like a header
    if res.get('contact', {}).get('email') and (not res['name'] or len(res['name'].split()) == 1):
        local = res['contact']['email'].split('@', 1)[0]
        local = re.sub(r'[._\-]+', ' ', local)
        inferred = ' '.join([w.capitalize() for w in local.split() if w])
        if inferred and len(inferred.split()) >= 1:
            # prefer inferred if current name is clearly not a proper name
            if not res['name'] or any(k in res['name'].lower() for k in ['resume', 'curriculum']):
                res['name'] = inferred

    # skills: look for 'SKILLS' section or common skill separators
    skill_section = []
    for i, line in enumerate(lines):
        if 'skill' in line.lower():
            # take next 1-3 lines as skills
            skill_section = lines[i:i+4]
            break
    if skill_section:
        skills = ", ".join(skill_section)
        tokens = [s.strip() for s in re.split('[,;\n|•\-]', skills) if s.strip()]
        res['skills'] = tokens
    else:
        # fallback: find comma-separated tech lists
        techs = []
        for line in lines[:20]:
            if any(k in line.lower() for k in ['python','java','sql','react','node','tensorflow','pytorch','llm','huggingface']):
                techs.extend([t.strip() for t in re.split('[,;|]', line) if t.strip()])
        res['skills'] = list(dict.fromkeys(techs))

    # education: look for 'UNIVERSITY', 'B.Tech', 'Bachelor', 'College'
    for line in lines:
        if any(k in line.lower() for k in ['university','b.tech','bachelor','college','master','msc','mba']):
            res['education'].append(line)

    # experience summary: first paragraph after header 'PROFESSIONAL' or first 2-3 lines of experience
    for i, line in enumerate(lines):
        if 'professional' in line.lower() or 'experience' == line.lower():
            snippet = lines[i+1:i+4]
            res['experience_summary'] = ' '.join(snippet)
            break

    return res
