import os
import time
import json
import requests
import hashlib
import re
from dotenv import load_dotenv
from typing import Optional, Tuple, List

from .cache import get as cache_get, set as cache_set

load_dotenv()

# Detect if the optional azure-ai-projects SDK is available. If present,
# we'll use it for Studio project endpoints; otherwise fall back to HTTP.
_HAS_AZURE_PROJECTS = False
AIProjectClient = None
AzureKeyCredential = None
DefaultAzureCredential = None
try:
    from azure.ai.projects import AIProjectClient  # type: ignore
    from azure.core.credentials import AzureKeyCredential  # type: ignore
    from azure.identity import DefaultAzureCredential  # type: ignore
    _HAS_AZURE_PROJECTS = True
except Exception:
    _HAS_AZURE_PROJECTS = False


class Chain:
    """Azure-backed Chain that calls the Azure Responses endpoint directly.

    Implements retries, trimming, simple caching, and compact prompts to reduce tokens.
    """
    def __init__(self, azure_api_key: Optional[str] = None, endpoint: Optional[str] = None, deployment: Optional[str] = None):
        self.azure_key = azure_api_key or os.getenv('AZURE_OPENAI_API_KEY')
        self.endpoint = endpoint or os.getenv('AZURE_OPENAI_ENDPOINT')
        # preferred deployment/model (default to a smaller Azure model for cost savings)
        self.deployment = deployment or os.getenv('AZURE_OPENAI_DEPLOYMENT') or 'gpt-35-turbo'
        self.last_error = None
        if not self.azure_key or not self.endpoint:
            raise RuntimeError('Azure endpoint or key not configured. Set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT.')

    def _trim_text(self, text: str, max_chars: int = 2000) -> str:
        if not text:
            return ''
        text = text.strip()
        if len(text) <= max_chars:
            return text
        # try to cut at nearest sentence boundary
        cut = text[:max_chars]
        m = re.search(r'([\.\!\?]\s)[^\.\!\?]*$', cut)
        if m:
            return cut[:m.start()+1]
        return cut

    def _call_azure_with_retry(self, payload: dict, retries: int = 3, backoff_base: float = 2.0):
        headers = {'api-key': self.azure_key, 'Content-Type': 'application/json'}
        attempt = 0
        # Determine the correct Azure Responses URL for several endpoint formats:
        # - Studio project endpoints (contain '/api/projects/')
        # - base resource endpoints like 'https://<name>.openai.azure.com'
        # - full Responses API URL already provided
        from urllib.parse import urlparse
        try:
            p = urlparse(self.endpoint)
            base = f"{p.scheme}://{p.netloc}"
            # If endpoint is a Studio project endpoint, prefer SDK path
            if '/api/projects/' in self.endpoint:
                target_url = None
            # If the endpoint already includes the openai/deployments path, use it as-is
            elif '/openai/deployments/' in self.endpoint:
                target_url = self.endpoint
            else:
                # Construct the chat/completions URL for the Azure OpenAI resource
                target_url = f"{base}/openai/deployments/{self.deployment}/chat/completions?api-version=2024-02-15-preview"
        except Exception:
            # fallback: attempt to use raw endpoint if parsing failed
            target_url = self.endpoint

        # If this is a Studio project endpoint and the azure-ai-projects SDK is available,
        # use the SDK which handles agent/project routing correctly.
        if _HAS_AZURE_PROJECTS and target_url is None:
            try:
                # Use the provided endpoint (which should be the project endpoint URL)
                project_endpoint = self.endpoint
                # Prefer AzureKeyCredential if an API key is present; otherwise DefaultAzureCredential
                cred = AzureKeyCredential(self.azure_key) if (AzureKeyCredential and self.azure_key) else DefaultAzureCredential()
                proj_client = AIProjectClient(endpoint=project_endpoint, credential=cred)
                openai_client = proj_client.get_openai_client()
                # Build input list expected by the SDK
                input_payload = payload.get('messages') or payload.get('input') or [{'role': 'user', 'content': payload.get('input', '')}]
                # Normalize messages -> list of dicts with role/content
                if isinstance(input_payload, list) and 'role' in input_payload[0]:
                    sdk_input = input_payload
                else:
                    sdk_input = [{'role': 'user', 'content': str(input_payload)}]

                # Try creating a response via SDK (supports agent_reference via extra_body)
                resp = openai_client.responses.create(input=sdk_input)
                # Try to return a JSON-like dict for downstream processing
                try:
                    text = getattr(resp, 'output_text', None) or json.dumps(resp.output) if getattr(resp, 'output', None) else str(resp)
                    return {'text': text}
                except Exception:
                    return {'text': str(resp)}
            except Exception as e:
                # Fall back to HTTP path below if SDK call fails
                self.last_error = str(e)
                # continue to HTTP fallback

        while True:
            try:
                resp = requests.post(target_url, headers=headers, json=payload, timeout=30)
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except Exception:
                        return {'text': resp.text}
                # handle rate limits and server errors with retry
                if resp.status_code in (429, 503, 502, 504) or 500 <= resp.status_code < 600:
                    attempt += 1
                    if attempt > retries:
                        self.last_error = resp.text
                        resp.raise_for_status()
                    time.sleep(backoff_base * attempt)
                    continue
                # other client error — raise
                resp.raise_for_status()
            except requests.RequestException as e:
                attempt += 1
                if attempt > retries:
                    self.last_error = str(e)
                    raise
                # if it's a transient network error, backoff and retry
                time.sleep(backoff_base * attempt)

    def _extract_text_from_response(self, resp_json: dict) -> str:
        # Prefer explicit assistant message paths used by Azure/OpenAI responses
        try:
            if not resp_json:
                return ''
            # SDK path or simplified dict with 'text'
            if isinstance(resp_json, dict) and 'text' in resp_json and isinstance(resp_json['text'], str):
                return resp_json['text']

            # OpenAI/Azure style response: choices -> message -> content
            if isinstance(resp_json, dict) and 'choices' in resp_json and isinstance(resp_json['choices'], list):
                for choice in resp_json['choices']:
                    # choice may have 'message' dict
                    if isinstance(choice, dict):
                        msg = choice.get('message') or choice.get('content') or choice.get('text')
                        if isinstance(msg, dict):
                            content = msg.get('content') or msg.get('text')
                            if isinstance(content, str) and content.strip():
                                return content
                        if isinstance(msg, str) and msg.strip():
                            return msg

            # 'output' -> may contain structured blocks
            if isinstance(resp_json, dict) and 'output' in resp_json:
                out = resp_json['output']
                if isinstance(out, str) and out.strip():
                    return out
                if isinstance(out, list):
                    for item in out:
                        if isinstance(item, dict):
                            # look for 'content' fields
                            c = item.get('content') or item.get('text')
                            if isinstance(c, str) and c.strip():
                                return c

            # Fallback: shallow search but avoid returning filter 'severity' strings like 'safe'
            def find_text(obj):
                if isinstance(obj, str):
                    if obj.strip().lower() in ('safe', 'unsafe', 'filtered'):
                        return None
                    return obj
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k.lower() in ('text', 'content', 'output') and isinstance(v, str):
                            if v.strip().lower() in ('safe', 'unsafe', 'filtered'):
                                continue
                            return v
                    for v in obj.values():
                        t = find_text(v)
                        if t:
                            return t
                if isinstance(obj, list):
                    for v in obj:
                        t = find_text(v)
                        if t:
                            return t
                return None

            t = find_text(resp_json)
            return t or ''
        except Exception:
            return ''

    def _log_usage(self, resp_json: dict, prompt_text: str):
        # Try to record token usage if provided by the provider; otherwise estimate roughly
        usage = {}
        if isinstance(resp_json, dict) and 'usage' in resp_json:
            usage = resp_json.get('usage')
        else:
            # rough estimate: 4 chars ~ 1 token
            out_text = self._extract_text_from_response(resp_json)
            usage = {
                'estimated_prompt_tokens': max(1, int(len(prompt_text) / 4)),
                'estimated_completion_tokens': max(1, int(len(out_text) / 4)),
            }

        os.makedirs(os.path.join('app', 'logs'), exist_ok=True)
        path = os.path.join('app', 'logs', 'token_usage.log')
        entry = {'ts': int(time.time()), 'model': self.deployment, 'usage': usage}
        try:
            with open(path, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def _azure_prompt_payload(self, prompt: str, temperature: float = 0.2, max_tokens: int = 1024) -> dict:
        # Build the payload expected by Azure Chat Completions API
        return {
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': max_tokens,
            'temperature': temperature,
        }

    def call_llm(self, prompt: str, cache_ttl: int = 3600, trim_to: Optional[int] = None) -> str:
        if trim_to:
            prompt = self._trim_text(prompt, trim_to)

        # cache key
        key = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
        cached = cache_get(key)
        if cached:
            return cached

        payload = self._azure_prompt_payload(prompt)
        try:
            resp = self._call_azure_with_retry(payload)
        except Exception as e:
            self.last_error = str(e)
            raise

        # log token usage (or estimates)
        try:
            self._log_usage(resp, prompt)
        except Exception:
            pass

        text = self._extract_text_from_response(resp)

        # If extracted text looks like a content-filter verdict or is very short,
        # log the raw provider response for debugging and avoid caching the sentinel.
        short_or_sentinal = not text or (isinstance(text, str) and len(text.strip()) < 12)
        if short_or_sentinal:
            try:
                os.makedirs(os.path.join('app', 'logs'), exist_ok=True)
                logpath = os.path.join('app', 'logs', 'azure_raw_responses.log')
                entry = {'ts': int(time.time()), 'prompt_hash': key, 'raw': resp}
                with open(logpath, 'a', encoding='utf-8') as fh:
                    fh.write(json.dumps(entry) + "\n")
            except Exception:
                pass

        # Only cache substantive outputs to avoid storing sentinels like 'safe'
        try:
            if isinstance(text, str) and len(text.strip()) >= 20:
                cache_set(key, text, ttl=cache_ttl)
        except Exception:
            pass

        return text

    def summarize_resume(self, resume_text: str, max_chars: int = 800) -> str:
        prompt = (
            "Summarize the following resume into a short professional summary (3-5 sentences) and list top skills as a comma-separated list. Return only plain text.\n\n" + resume_text
        )
        return self.call_llm(prompt, cache_ttl=24 * 3600, trim_to=max_chars)

    def extract_skills_no_llm(self, resume_text: str) -> List[str]:
        # Heuristic extraction: look for a Skills section or comma/line-separated skills
        skills = []
        try:
            m = re.search(r"(?ims)skills[:\s]*\n(.{1,500})", resume_text)
            block = None
            if m:
                block = m.group(1)
            else:
                # try to find 'Skills -' inline
                m2 = re.search(r"(?im)(Skills)[:\-]\s*(.*)", resume_text)
                if m2:
                    block = m2.group(2)

            if block:
                # split by commas or newlines
                parts = re.split(r'[\n,;|\\/]+', block)
                for p in parts:
                    p = p.strip()
                    if p and len(p) > 1:
                        skills.append(p)
        except Exception:
            pass
        # fallback: find frequent technology words
        if not skills:
            candidates = re.findall(r"\b(Python|JavaScript|Java|C\+\+|C#|SQL|AWS|GCP|Azure|TensorFlow|PyTorch|React|Django|Flask|Docker|Kubernetes)\b", resume_text, flags=re.I)
            skills = list({c.strip() for c in candidates})
        return [s.strip() for s in skills]

    def match_skills(self, job_skills: List[str], resume_skills: List[str]) -> Tuple[List[str], List[str]]:
        js = [s.lower() for s in (job_skills or [])]
        rs = [s.lower() for s in (resume_skills or [])]
        matched = [s for s in js if s in rs]
        missing = [s for s in js if s not in rs]
        return matched, missing
    def _sanitize_text(self, text: str) -> str:
        if not isinstance(text, str):
            try:
                text = str(text)
            except Exception:
                return ''
        # Normalize whitespace and remove control characters
        text = re.sub(r"\s+", " ", text).strip()
        return text
    def parse_resume(self, resume_text: str) -> dict:
        """Parse resume text into structured JSON (name, contact, education, skills, experience).

        Uses the Azure-backed `call_llm` helper and falls back to a simple heuristic if parsing fails.
        """
        prompt = (
            "Parse the following resume text and return a JSON object with keys: name, contact, education, skills (list), experience (list of roles with dates), summary."
            "\n\nRESUME TEXT:\n" + resume_text + "\n\nReturn only valid JSON."
        )

        try:
            resp_text = self.call_llm(prompt, cache_ttl=3600, trim_to=3000)
        except Exception as e:
            self.last_error = str(e)
            # fallback heuristic
            try:
                from .resume_parser import extract_basic_resume_info
                return extract_basic_resume_info(resume_text)
            except Exception:
                return {"name": None, "contact": {}, "education": [], "skills": [], "experience": [], "summary": None}

        # try to parse JSON
        try:
            parsed = json.loads(resp_text)
            return parsed
        except Exception:
            # fallback: return heuristic extraction
            try:
                from .resume_parser import extract_basic_resume_info
                return extract_basic_resume_info(resume_text)
            except Exception:
                return {"name": None, "contact": {}, "education": [], "skills": [], "experience": [], "summary": None}

    def extract_job_poster(self, job_page_text: str):
        prompt = (
            "From the job page text below, extract any hiring contact or poster information and return a JSON object with keys: posted_on, poster_name, poster_link, poster_profile, contact_email. If not present, use null. Return only valid JSON.\n\n" + job_page_text
        )
        try:
            resp = self.call_llm(prompt, cache_ttl=3600, trim_to=1500)
        except Exception as e:
            self.last_error = str(e)
            return {"posted_on": None, "poster_name": None, "poster_link": None, "poster_profile": None, "contact_email": None}

        try:
            parsed = json.loads(resp)
        except Exception:
            # best-effort: try to regex an email
            m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", job_page_text)
            return {"posted_on": None, "poster_name": None, "poster_link": None, "poster_profile": None, "contact_email": m.group(0) if m else None}
        return parsed

    def extract_jobs(self, page_text: str):
        """Extract one or more job entries from a job page text and return a list of job dicts.

        Each job dict should contain at least: `role`, `location`, `skills` (list), `description`.
        """
        prompt_extract = (
            "From the job page text below, extract one or more job postings. For each posting return a JSON object with keys: role, location, skills (list), description (full text). Return a JSON array only.\n\n" + page_text
        )

        try:
            res_text = self.call_llm(prompt_extract, cache_ttl=3600, trim_to=3000)
        except Exception as e:
            self.last_error = e
            msg_low = str(e).lower()
            # If request is too large, fall back to a lightweight heuristic extraction
            if 'request_too_large' in msg_low or 'request entity too large' in msg_low or '413' in msg_low:
                # simple heuristic: try to extract role/location using common page elements
                try:
                    import re
                    role = None
                    location = None
                    m_role = re.search(r"(?im)^(?:Job\s*Title|Title)\s*[:\-]\s*(.+)$", page_text)
                    if m_role:
                        role = m_role.group(1).strip()
                    m_loc = re.search(r"(?im)^Location\s*[:\-]\s*(.+)$", page_text)
                    if m_loc:
                        location = m_loc.group(1).strip()
                    # fallback to <title> or <h1>
                    if not role:
                        m_title = re.search(r"<title\s*>([^<]+)</title>", page_text, flags=re.I)
                        if m_title:
                            role = m_title.group(1).strip()
                    if not role:
                        m_h1 = re.search(r"<h1[^>]*>([^<]+)</h1>", page_text, flags=re.I)
                        if m_h1:
                            role = m_h1.group(1).strip()
                    # try meta location
                    if not location:
                        m_meta_loc = re.search(r"<meta[^>]+name=[\'\"]?location[\'\"]?[^>]+content=[\'\"]([^\'\"]+)[\'\"]", page_text, flags=re.I)
                        if m_meta_loc:
                            location = m_meta_loc.group(1).strip()
                    return [{"role": role, "location": location, "skills": [], "description": page_text}]
                except Exception:
                    return [{"role": None, "location": None, "skills": [], "description": page_text}]
            else:
                if 'model_not_found' in msg_low or 'does not exist' in msg_low or 'decommission' in msg_low:
                    self.last_error = msg_low
                    raise
                else:
                    raise

        try:
            parsed = json.loads(res_text)
        except Exception:
            self.last_error = 'Output parsing failed for job extraction'
            return [{"role": None, "location": None, "skills": [], "description": page_text}]

        return parsed if isinstance(parsed, list) else [parsed]

    def write_mail_with_resume(self, job, resume_info, missing_requirements=None):
        # Use the provided concise email template. Keep token usage low by providing resume summary if available.
        resume_summary = resume_info.get('summary') if isinstance(resume_info, dict) else None
        if not resume_summary:
            try:
                resume_summary = self.summarize_resume(json.dumps(resume_info) if isinstance(resume_info, dict) else str(resume_info))
            except Exception:
                resume_summary = ''

        # Build a structured prompt asking the model to return JSON with specific fields.
        job_json = json.dumps(job) if isinstance(job, dict) else str(job)
        prompt = (
            f"You are a hiring-focused AI assistant specialized in crafting high-conversion job application emails.\n\n"
            f"Candidate Resume Summary:\n{resume_summary}\n\n"
            f"Job Description:\n{job_json}\n\n"
            "Task: Generate a personalized job application email that is ready-to-send without further edits.\n"
            "Instructions:\n"
            "1) Return ONLY valid JSON (no surrounding text).\n"
            "2) JSON keys: subject (string), body (string), ready_to_send (true/false), notes (string explaining any anomalies), role_exact (the role string exactly as found in the job description), job_url (string).\n"
            "3) Fill placeholders: if any placeholders like [Your Name] or [Company Name] appear, replace them using the resume data if available.\n"
            "4) Keep the body concise (120-170 words) and include top 3 matching skills.\n"
            "5) Ensure the subject line includes the role and location if present.\n"
            "6) If you cannot confidently fill a field, set ready_to_send to false and explain why in notes.\n"
            "Provide the JSON now."
        )

        try:
            out = self.call_llm(prompt, cache_ttl=3600, trim_to=1200)
        except Exception as e:
            self.last_error = str(e)
            raise

        # Try to parse the model's JSON output. If the model returned text containing
        # a JSON object (wrapped in additional commentary), attempt to extract and parse
        # the first balanced JSON object before falling back to wrapping the raw text.
        mail_obj = None
        try:
            mail_obj = json.loads(out)
        except Exception:
            text = out or ''

            def _extract_first_json(s: str):
                start = s.find('{')
                if start == -1:
                    return None
                stack = 0
                for i in range(start, len(s)):
                    ch = s[i]
                    if ch == '{':
                        stack += 1
                    elif ch == '}':
                        stack -= 1
                        if stack == 0:
                            return s[start:i+1]
                return None

            blob = _extract_first_json(text)
            if blob:
                try:
                    mail_obj = json.loads(blob)
                except Exception:
                    mail_obj = None

            if not mail_obj:
                # Build a fallback JSON structure wrapping the raw output
                mail_obj = {
                    'subject': (f"Application for {job.get('role')}") if isinstance(job, dict) else 'Application',
                    'body': text,
                    'ready_to_send': True if text and '[Your' not in text else False,
                    'notes': 'Provider did not return JSON; wrapped raw output.',
                    'role_exact': job.get('role') if isinstance(job, dict) else None,
                    'job_url': job.get('source_url') if isinstance(job, dict) else None,
                }

        # If the provider returned raw text that includes a leading 'Subject:' line,
        # try to extract the subject and body into the structured fields.
        try:
            if isinstance(mail_obj.get('body'), str):
                body_text = mail_obj['body']
                msub = re.search(r"(?ims)^\s*Subject\s*:\s*(.+?)(?:\n\s*\n|\n)", body_text)
                if msub:
                    subj = msub.group(1).strip()
                    rest = body_text[msub.end():].strip()
                    mail_obj['subject'] = subj
                    mail_obj['body'] = rest
        except Exception:
            pass

        # Auto-fill common placeholders using resume_info
        def _fill_placeholders(s: str) -> str:
            if not isinstance(s, str):
                return s
            name = resume_info.get('name') if isinstance(resume_info, dict) else None
            contact = resume_info.get('contact') if isinstance(resume_info, dict) else None
            linkedin = None
            if contact and isinstance(contact, dict):
                linkedin = contact.get('linkedin') or contact.get('profile')
            replacements = {
                '[Your Full Name]': name or '',
                '[Your Name]': name or '',
                '[Your Contact Information]': ', '.join(filter(None, [
                    (contact.get('email') if isinstance(contact, dict) else None),
                    (contact.get('phone') if isinstance(contact, dict) else None)
                ])) if contact else '',
                '[Your LinkedIn Profile]': linkedin or '',
                '[Company Name]': job.get('company') if isinstance(job, dict) else '',
                '[Job Title]': job.get('role') if isinstance(job, dict) else '',
            }
            # Accept common alternate placeholder variants
            alt_map = {
                '[Candidate Name]': name or '',
                '[Email]': (contact.get('email') if isinstance(contact, dict) else '') or '',
                '[Phone]': (contact.get('phone') if isinstance(contact, dict) else '') or '',
                '[Your Email]': (contact.get('email') if isinstance(contact, dict) else '') or '',
                '[Your Phone]': (contact.get('phone') if isinstance(contact, dict) else '') or '',
                '[your email]': (contact.get('email') if isinstance(contact, dict) else '') or '',
                '[your phone]': (contact.get('phone') if isinstance(contact, dict) else '') or '',
                '[Contact]': ', '.join(filter(None, [contact.get('email') if isinstance(contact, dict) else None, contact.get('phone') if isinstance(contact, dict) else None])) if contact else '',
                '[Contact Information]': ', '.join(filter(None, [contact.get('email') if isinstance(contact, dict) else None, contact.get('phone') if isinstance(contact, dict) else None])) if contact else '',
            }
            replacements.update(alt_map)
            for k, v in replacements.items():
                if v:
                    s = s.replace(k, v)
            return s

        try:
            mail_obj['subject'] = _fill_placeholders(mail_obj.get('subject') or '')
            mail_obj['body'] = _fill_placeholders(mail_obj.get('body') or '')
            # Ensure role_exact and job_url fields exist
            if 'role_exact' not in mail_obj:
                mail_obj['role_exact'] = job.get('role') if isinstance(job, dict) else None
            if 'job_url' not in mail_obj:
                mail_obj['job_url'] = job.get('source_url') if isinstance(job, dict) else None

            # Validate for remaining placeholders
            placeholders = ['[Your', '[Company', '[Job Title', '[Your Contact']
            if any(p in (mail_obj.get('subject','') + mail_obj.get('body','')) for p in placeholders):
                # try a second pass: if resume_info has more fields, replace common variants
                mail_obj['body'] = _fill_placeholders(mail_obj['body'])
                mail_obj['subject'] = _fill_placeholders(mail_obj['subject'])

            # Final ready_to_send: ensure required contact info is present
            if not mail_obj.get('ready_to_send'):
                # If body/subject contains no obvious placeholders and resume has contact info, set ready
                has_contact = False
                if isinstance(resume_info, dict) and isinstance(resume_info.get('contact'), dict):
                    c = resume_info['contact']
                    if c.get('email') or c.get('phone'):
                        has_contact = True
                if has_contact and ('[Your' not in (mail_obj.get('body') + mail_obj.get('subject'))):
                    mail_obj['ready_to_send'] = True

            # sanitize text fields
            mail_obj['subject'] = self._sanitize_text(mail_obj.get('subject') or '')
            mail_obj['body'] = self._sanitize_text(mail_obj.get('body') or '')
            mail_obj['notes'] = self._sanitize_text(mail_obj.get('notes') or '')
        except Exception:
            pass

        return mail_obj

    def write_mail(self, job, links):
        prompt_email = (
            f"You are Mohan, a business development executive at AtliQ. Write a concise cold email (no preamble) pitching AtliQ's capability to meet the needs in the job description below.\n\n"
            f"Job Description:\n{json.dumps(job) if isinstance(job, dict) else str(job)}\n\n"
            f"Include the most relevant portfolio links: {links}\n\nOutput: Subject line and Email body only."
        )
        out = self.call_llm(prompt_email, cache_ttl=3600, trim_to=800)
        return self._sanitize_text(out)

    @staticmethod
    def probe_model(groq_api_key: str, model_name: str, timeout_seconds: int = 10) -> dict:
        """Try to instantiate a small ChatGroq and run a tiny prompt to check availability.

        Returns dict: {"ok": bool, "model": model_name, "error": str or None}
        """
        from langchain_groq import ChatGroq
        from langchain_core.prompts import PromptTemplate
        try:
            test_llm = ChatGroq(temperature=0, groq_api_key=groq_api_key, model_name=model_name)
        except Exception as e:
            return {"ok": False, "model": model_name, "error": str(e)}

        try:
            prompt = PromptTemplate.from_template("Say OK as a single word.")
            chain = prompt | test_llm
            res = chain.invoke({})
            return {"ok": True, "model": model_name, "error": None, "response_preview": getattr(res, 'content', str(res))}
        except Exception as e:
            return {"ok": False, "model": model_name, "error": str(e)}


if __name__ == "__main__":
    print(os.getenv("GROQ_API_KEY"))