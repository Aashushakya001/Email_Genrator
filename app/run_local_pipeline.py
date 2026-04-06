#!/usr/bin/env python3
import pathlib
import sys
# ensure repo root on sys.path when running script directly
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.job_page_fetch_and_extract import fetch, heuristic_extract
from app.resume_parser import extract_text_from_pdf, extract_basic_resume_info
import json

PDF_PATH = str(_PROJECT_ROOT / 'resume_Ayush_shakya11.pdf')
JOB_URL = "https://www.accenture.com/in-en/careers/jobdetails?id=ATCI-4822077-S1849385_en"


def simple_email_fallback(job, resume_info):
    name = resume_info.get('name') or 'Candidate'
    role = job.get('role') or 'the role'
    loc = job.get('location') or ''
    skills = resume_info.get('skills') or []
    top_skills = ', '.join(skills[:3]) if skills else ''

    subj = f"Application for {role} - {name}"

    # Build a concise ~120 word body using resume_info heuristics
    body_lines = []
    body_lines.append(f"Hello,")
    body_lines.append("")
    intro = f"I am {name} and I am applying for the {role} position{(' in ' + loc) if loc else ''}."
    body_lines.append(intro)

    if top_skills:
        body_lines.append(f"My key skills include: {top_skills}.")

    # include experience summary if present
    exp = resume_info.get('experience_summary') or resume_info.get('summary') or ''
    if exp:
        body_lines.append(f"Briefly, {exp}")

    body_lines.append("I am excited about the opportunity to contribute and would welcome the chance to discuss how my background can help your team.")
    body_lines.append("")
    body_lines.append("Best regards,")
    body_lines.append(name)

    # join and keep reasonably short
    body = "\n".join(body_lines)
    return subj, body


def run():
    print('Fetching job page...')
    page = fetch(JOB_URL)
    print('Fetched bytes:', len(page))

    job = heuristic_extract(page)
    print('Heuristic job extraction:', json.dumps(job, indent=2)[:1000])

    print('Reading sample resume PDF:', PDF_PATH)
    try:
        text = extract_text_from_pdf(PDF_PATH)
        resume_info = extract_basic_resume_info(text)
    except Exception as e:
        print('Error reading/parsing PDF:', e)
        resume_info = {"name": "Candidate", "skills": []}

    print('Parsed resume info:', json.dumps(resume_info, indent=2)[:1000])

    subj, body = simple_email_fallback(job, resume_info)

    print('\n=== GENERATED FALLBACK EMAIL ===\n')
    print('Subject:', subj)
    print('\n' + body)


if __name__ == '__main__':
    run()
