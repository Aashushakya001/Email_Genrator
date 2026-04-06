#!/usr/bin/env python3
import os
import re
import json
import pathlib
import sys
from typing import Dict

# Ensure repo root
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env from `app/.env` so provided Azure credentials are available to this script
from dotenv import load_dotenv
env_path = _PROJECT_ROOT.joinpath('app', '.env')
if env_path.exists():
    load_dotenv(str(env_path))

from app.job_page_fetch_and_extract import fetch
from app.resume_parser import extract_text_from_pdf, extract_basic_resume_info
from app.chains import Chain

JOB_URL = "https://www.accenture.com/in-en/careers/jobdetails?id=ATCI-4822077-S1849385_en"
PDF_PATH = str(_PROJECT_ROOT / 'resume_Ayush_shakya11.pdf')


def extract_job_parts(page_text: str) -> Dict[str, str]:
    """Extract role, location, description, requirements from raw HTML using heuristics."""
    out = {'role': None, 'location': None, 'description': None, 'requirements': None}

    # 1) data attributes (site includes data-jobtitle / data-joblocation)
    m_title = re.search(r'data-jobtitle=["\']([^"\']+)["\']', page_text, flags=re.I)
    m_loc = re.search(r'data-joblocation=["\']([^"\']+)["\']', page_text, flags=re.I)
    if m_title:
        out['role'] = m_title.group(1).strip()
    if m_loc:
        out['location'] = m_loc.group(1).strip()

    # 2) <h1>
    if not out['role']:
        m_h1 = re.search(r"<h1[^>]*>([^<]+)</h1>", page_text, flags=re.I)
        if m_h1:
            out['role'] = m_h1.group(1).strip()

    # 3) Job Description block: look for the accordion content under "Job Description"
    desc = None
    try:
        # Find the Job Description header then the following content block
        m = re.search(r'(?:Job Description|Job Description</h2>)(.*?)<div class="rad-accordion-atom__content-wrapper', page_text, flags=re.I | re.S)
        if m:
            # try to find the first content div after the header
            rest = page_text[m.start():m.start()+5000]
            m2 = re.search(r'<div class="rad-accordion-atom__content">(.*?)</div>', page_text[m.start():m.start()+50000], flags=re.S | re.I)
            if m2:
                desc = re.sub(r'<[^>]+>', '', m2.group(1)).strip()
    except Exception:
        desc = None

    # fallback: search for 'Project Role Description' or 'Job Description' paragraphs
    if not desc:
        m_pd = re.search(r'Project Role Description : </b>(.*?)<br', page_text, flags=re.I | re.S)
        if m_pd:
            desc = re.sub(r'<[^>]+>', '', m_pd.group(1)).strip()

    # final fallback: grab a reasonable chunk around 'Job Description' heading
    if not desc:
        m_chunk = re.search(r'Job Description.*?(?:<div|</section>)', page_text, flags=re.I | re.S)
        if m_chunk:
            desc = re.sub(r'<[^>]+>', '', m_chunk.group(0)).strip()

    out['description'] = desc

    # 4) Requirements / Must have skills
    req = None
    m_req = re.search(r'(?:Must have skills|Must have solid experience|Must have).*?:\s*(.*?)<br', page_text, flags=re.I | re.S)
    if m_req:
        req = re.sub(r'<[^>]+>', '', m_req.group(1)).strip()

    # Try to find "Required Skill:" occurrences
    if not req:
        m_rs = re.search(r'Required Skill:\s*</span>\s*<span[^>]*>([^<]+)</span>', page_text, flags=re.I)
        if m_rs:
            req = m_rs.group(1).strip()

    # Another pattern in the page: 'Must have solid experience developing...' capture sentence
    if not req:
        m_sent = re.search(r'Must have[^.]{0,200}\.', page_text, flags=re.I)
        if m_sent:
            req = re.sub(r'<[^>]+>', '', m_sent.group(0)).strip()

    out['requirements'] = req

    # Clean whitespace
    for k, v in out.items():
        if isinstance(v, str):
            out[k] = re.sub(r"\s+", " ", v).strip()
    return out


def best_prompt_for_email(job: Dict[str, str], resume_info: Dict[str, str]) -> str:
    # Build a compact, high-quality prompt for LLM to generate an application email
    job_summary = []
    if job.get('role'):
        job_summary.append(f"Role: {job['role']}")
    if job.get('location'):
        job_summary.append(f"Location: {job['location']}")
    if job.get('requirements'):
        job_summary.append(f"Key requirements: {job['requirements']}")

    job_block = "; ".join(job_summary)

    resume_skills = ', '.join(resume_info.get('skills')[:8]) if resume_info.get('skills') else ''
    resume_name = resume_info.get('name') or 'Candidate'
    resume_summary = resume_info.get('experience_summary') or resume_info.get('summary') or ''
    # Compute simple matched skills using token overlap (robust to variations like 'ML'/'Machine Learning')
    matched = []
    try:
        job_reqs = (job.get('requirements') or '').lower()
        for s in resume_info.get('skills') or []:
            s_low = s.lower()
            # split into alphanumeric tokens
            tokens = [t for t in re.split(r"[^a-z0-9]+", s_low) if len(t) > 1]
            if any(token in job_reqs for token in tokens):
                matched.append(s.strip())
        # also try checking if job keywords appear in resume skill string
        if not matched and job_reqs:
            jtokens = [t for t in re.split(r"[^a-z0-9]+", job_reqs) if len(t) > 2]
            for s in resume_info.get('skills') or []:
                s_low = s.lower()
                if any(jt in s_low for jt in jtokens):
                    matched.append(s.strip())
    except Exception:
        matched = []
    matched_skills = ', '.join(dict.fromkeys(matched))[:200]

    prompt = (
        "You are an expert hiring assistant.\n"
        "Task: Write a short, high-conversion job application email (Subject line + Email body) tailored to the job and candidate information below. Keep body 110-150 words, confident professional tone, emphasize top 3 matched skills, measurable impact, and a clear call-to-action to arrange an interview. Avoid buzzwords and generic fluff. Output only plain text starting with 'Subject:' then a blank line then the email body.\n\n"
        "JOB: " + job_block + "\n\n"
        "JOB FULL DESCRIPTION:\n" + (job.get('description') or '') + "\n\n"
        "CANDIDATE:\nName: " + resume_name + "\nSkills: " + resume_skills + "\nMatched skills: " + matched_skills + "\nSummary: " + (resume_summary or '') + "\n\n"
        "Also: which top 3 skills from the resume best match the job? Provide them inline in the email introduction.\n"
    )
    return prompt


def llm_or_fallback(prompt: str) -> str:
    # If AZURE env is present, use Chain.call_llm; otherwise use deterministic fallback templating
    key = os.getenv('AZURE_OPENAI_API_KEY')
    endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
    deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT') or 'gpt-35-turbo'

    print('DEBUG: AZURE key present?', bool(key), 'endpoint present?', bool(endpoint))
    if key and endpoint:
        try:
            print('DEBUG: Attempting to call Chain.call_llm')
            chain = Chain(azure_api_key=key, endpoint=endpoint, deployment=deployment)
            # Avoid returning stale cached responses by adding a short nonce to the prompt
            import time
            nonce_prompt = prompt + "\n\n#nonce:" + str(int(time.time()))
            resp_text = chain.call_llm(nonce_prompt, cache_ttl=0, trim_to=1800)
            print('LLM raw output:', repr(resp_text)[:200])
            # If the provider returned an unexpected short sentinel like 'safe', fetch raw provider response
            if isinstance(resp_text, str) and resp_text.strip().lower() in ('safe', 'ok', 'error'):
                try:
                    payload = chain._azure_prompt_payload(nonce_prompt)
                    raw = chain._call_azure_with_retry(payload)
                    print('Raw provider response (debug):')
                    print(raw if isinstance(raw, (str, dict)) else str(raw)[:2000])
                    if chain.last_error:
                        print('Chain.last_error:', chain.last_error)
                    # attempt to extract assistant message content from raw response
                    if isinstance(raw, dict):
                        try:
                            choices = raw.get('choices') or raw.get('choices', [])
                            if choices and isinstance(choices, list):
                                msg = choices[0].get('message') if isinstance(choices[0], dict) else None
                                if msg and isinstance(msg, dict) and 'content' in msg:
                                    provider_text = msg.get('content')
                                    print('\nExtracted provider message content (used as output):\n')
                                    print(provider_text)
                                    return provider_text
                                # older shape: choices[0]['message']['content'] may be nested
                                # sometimes content is under choices[0]['message']['content'] already handled
                                # else, try 'choices'[0]['content']
                                if choices and isinstance(choices[0], dict) and 'content' in choices[0]:
                                    provider_text = choices[0]['content']
                                    print('\nExtracted provider content (alt):\n')
                                    print(provider_text)
                                    return provider_text
                        except Exception:
                            pass
                except Exception as e:
                    print('Failed to fetch raw provider response:', e)
            return resp_text
        except Exception as e:
            print('LLM call failed:', e)
            print('Falling back to deterministic generator')

    # Fallback deterministic generator: assemble a fully filled email from extracted fields
    def deterministic_email_from_prompt(p: str) -> str:
        # extract fields from prompt
        m_role = re.search(r'Role:\s*([^;\n]+)', p)
        m_loc = re.search(r'Location:\s*([^;\n]+)', p)
        m_matched = re.search(r'Matched skills:\s*([^\n]+)', p)
        m_name = re.search(r'Name:\s*([^\n]+)', p)
        m_skills = re.search(r'Skills:\s*([^\n]+)', p)
        m_summary = re.search(r'Summary:\s*(.+)', p, flags=re.S)

        role = m_role.group(1).strip() if m_role else 'the position'
        location = m_loc.group(1).strip() if m_loc else None
        matched = m_matched.group(1).strip() if m_matched else ''
        name = m_name.group(1).strip() if m_name else 'Candidate'
        skills = [s.strip() for s in (m_skills.group(1).split(',') if m_skills else []) if s.strip()]
        summary = (m_summary.group(1).strip() if m_summary else '')

        # try to infer company from the JOB_URL constant if present
        company = None
        try:
            from urllib.parse import urlparse
            host = urlparse(JOB_URL).netloc
            company = host.split('.')[-2].capitalize() if host else None
        except Exception:
            company = None

        subj = f"Application for {role} - {name}"

        # Compose a concise, filled email body
        lines = []
        greeting = f"Hello {company or 'Hiring Team'},"
        lines.append(greeting)
        lines.append("")
        intro = f"My name is {name} and I am writing to express my interest in the {role}{(' in ' + location) if location else ''} role{(' at ' + company) if company else ''}."
        lines.append(intro)
        if matched:
            lines.append(f"I bring experience with {matched}, which directly match the key requirements for this opening.")
        elif skills:
            lines.append(f"My core skills include {', '.join(skills[:3])}.")

        if summary:
            # keep summary short
            lines.append(summary if len(summary) < 220 else summary[:220] + '...')

        lines.append("I would welcome the opportunity to discuss how my background and experience can help your team meet its goals. Please let me know a convenient time to speak or any next steps.")
        lines.append("")
        lines.append("Best regards,")
        lines.append(name)

        return "Subject: " + subj + "\n\n" + "\n".join(lines)

    return deterministic_email_from_prompt(prompt)


def run():
    print('Fetching job page...')
    page = fetch(JOB_URL)
    print('Fetched bytes:', len(page))

    job = extract_job_parts(page)
    print('\n--- Extracted Job Parts ---')
    print('Role:', job['role'])
    print('Location:', job['location'])
    print('Requirements:', job['requirements'])
    print('Description (first 500 chars):')
    print((job['description'] or '')[:500])

    print('\nParsing sample resume...')
    try:
        text = extract_text_from_pdf(PDF_PATH)
        resume_info = extract_basic_resume_info(text)
    except Exception as e:
        print('Resume parse error:', e)
        resume_info = {"name": "Candidate", "skills": [], "experience_summary": None}

    print('\n--- Parsed Resume ---')
    print('Name:', resume_info.get('name'))
    print('Top skills:', resume_info.get('skills')[:8])
    print('Experience summary:', resume_info.get('experience_summary') or '')

    # attach source URL
    job['source_url'] = JOB_URL

    # Show computed matched skills for debugging
    try:
        prompt = best_prompt_for_email(job, resume_info)
        m_ms = re.search(r'Matched skills:\s*([^\n]+)', prompt)
        print('\nComputed matched skills:', m_ms.group(1) if m_ms else '')
    except Exception:
        prompt = None

    print('\nGenerating structured email...')

    # Try to use Chain.write_mail_with_resume (preferred). Fall back to llm_or_fallback if Chain cannot be instantiated.
    mail_obj = None
    try:
        chain = Chain()
        mail_obj = chain.write_mail_with_resume(job, resume_info, None)
    except Exception as e:
        print('Chain unavailable or failed:', e)
        # fall back to earlier behavior
        out = llm_or_fallback(prompt or best_prompt_for_email(job, resume_info))
        mail_obj = {'subject': None, 'body': out, 'ready_to_send': False, 'notes': 'Fallback raw output', 'role_exact': job.get('role'), 'job_url': JOB_URL}

    print('\n--- GENERATED (structured) ---')
    try:
        print(json.dumps(mail_obj, indent=2, ensure_ascii=False))
    except Exception:
        print(mail_obj)

    print('\n--- Ready-to-send email body ---\n')
    try:
        print(mail_obj.get('body') if isinstance(mail_obj, dict) else str(mail_obj))
    except Exception:
        print(mail_obj)


if __name__ == '__main__':
    run()
