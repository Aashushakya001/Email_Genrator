# import os
# import time
# import json
# import requests
# import hashlib
# import re
# from dotenv import load_dotenv
# from typing import Optional, Tuple, List

# from .cache import get as cache_get, set as cache_set

# load_dotenv()

# # Detect if the optional azure-ai-projects SDK is available. If present,
# # we'll use it for Studio project endpoints; otherwise fall back to HTTP.
# _HAS_AZURE_PROJECTS = False
# AIProjectClient = None
# AzureKeyCredential = None
# DefaultAzureCredential = None
# try:
#     from azure.ai.projects import AIProjectClient  # type: ignore
#     from azure.core.credentials import AzureKeyCredential  # type: ignore
#     from azure.identity import DefaultAzureCredential  # type: ignore
#     _HAS_AZURE_PROJECTS = True
# except Exception:
#     _HAS_AZURE_PROJECTS = False


# class Chain:
#     """Azure-backed Chain that calls the Azure Responses endpoint directly.

#     Implements retries, trimming, simple caching, and compact prompts to reduce tokens.
#     """
#     def __init__(self, azure_api_key: Optional[str] = None, endpoint: Optional[str] = None, deployment: Optional[str] = None):
#         self.azure_key = azure_api_key or os.getenv('AZURE_OPENAI_API_KEY')
#         self.endpoint = endpoint or os.getenv('AZURE_OPENAI_ENDPOINT')
#         # preferred deployment/model (default to a smaller Azure model for cost savings)
#         self.deployment = deployment or os.getenv('AZURE_OPENAI_DEPLOYMENT') or 'gpt-35-turbo'
#         self.last_error = None
#         if not self.azure_key or not self.endpoint:
#             raise RuntimeError('Azure endpoint or key not configured. Set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT.')

#     def _trim_text(self, text: str, max_chars: int = 2000) -> str:
#         if not text:
#             return ''
#         text = text.strip()
#         if len(text) <= max_chars:
#             return text
#         # try to cut at nearest sentence boundary
#         cut = text[:max_chars]
#         m = re.search(r'([\.\!\?]\s)[^\.\!\?]*$', cut)
#         if m:
#             return cut[:m.start()+1]
#         return cut

#     def _call_azure_with_retry(self, payload: dict, retries: int = 3, backoff_base: float = 2.0):
#         headers = {'api-key': self.azure_key, 'Content-Type': 'application/json'}
#         attempt = 0
#         # Determine the correct Azure Responses URL for several endpoint formats:
#         # - Studio project endpoints (contain '/api/projects/')
#         # - base resource endpoints like 'https://<name>.openai.azure.com'
#         # - full Responses API URL already provided
#         from urllib.parse import urlparse
#         try:
#             p = urlparse(self.endpoint)
#             base = f"{p.scheme}://{p.netloc}"
#             # If endpoint is a Studio project endpoint, prefer SDK path
#             if '/api/projects/' in self.endpoint:
#                 target_url = None
#             # If the endpoint already includes the openai/deployments path, use it as-is
#             elif '/openai/deployments/' in self.endpoint:
#                 target_url = self.endpoint
#             else:
#                 # Construct the chat/completions URL for the Azure OpenAI resource
#                 target_url = f"{base}/openai/deployments/{self.deployment}/chat/completions?api-version=2024-02-15-preview"
#         except Exception:
#             # fallback: attempt to use raw endpoint if parsing failed
#             target_url = self.endpoint

#         # If this is a Studio project endpoint and the azure-ai-projects SDK is available,
#         # use the SDK which handles agent/project routing correctly.
#         if _HAS_AZURE_PROJECTS and target_url is None:
#             try:
#                 # Use the provided endpoint (which should be the project endpoint URL)
#                 project_endpoint = self.endpoint
#                 # Prefer AzureKeyCredential if an API key is present; otherwise DefaultAzureCredential
#                 cred = AzureKeyCredential(self.azure_key) if (AzureKeyCredential and self.azure_key) else DefaultAzureCredential()
#                 proj_client = AIProjectClient(endpoint=project_endpoint, credential=cred)
#                 openai_client = proj_client.get_openai_client()
#                 # Build input list expected by the SDK
#                 input_payload = payload.get('messages') or payload.get('input') or [{'role': 'user', 'content': payload.get('input', '')}]
#                 # Normalize messages -> list of dicts with role/content
#                 if isinstance(input_payload, list) and 'role' in input_payload[0]:
#                     sdk_input = input_payload
#                 else:
#                     sdk_input = [{'role': 'user', 'content': str(input_payload)}]

#                 # Try creating a response via SDK (supports agent_reference via extra_body)
#                 resp = openai_client.responses.create(input=sdk_input)
#                 # Try to return a JSON-like dict for downstream processing
#                 try:
#                     text = getattr(resp, 'output_text', None) or json.dumps(resp.output) if getattr(resp, 'output', None) else str(resp)
#                     return {'text': text}
#                 except Exception:
#                     return {'text': str(resp)}
#             except Exception as e:
#                 # Fall back to HTTP path below if SDK call fails
#                 self.last_error = str(e)
#                 # continue to HTTP fallback

#         while True:
#             try:
#                 resp = requests.post(target_url, headers=headers, json=payload, timeout=30)
#                 if resp.status_code == 200:
#                     try:
#                         return resp.json()
#                     except Exception:
#                         return {'text': resp.text}
#                 # handle rate limits and server errors with retry
#                 if resp.status_code in (429, 503, 502, 504) or 500 <= resp.status_code < 600:
#                     attempt += 1
#                     if attempt > retries:
#                         self.last_error = resp.text
#                         resp.raise_for_status()
#                     time.sleep(backoff_base * attempt)
#                     continue
#                 # other client error — raise
#                 resp.raise_for_status()
#             except requests.RequestException as e:
#                 attempt += 1
#                 if attempt > retries:
#                     self.last_error = str(e)
#                     raise
#                 # if it's a transient network error, backoff and retry
#                 time.sleep(backoff_base * attempt)

#     def _extract_text_from_response(self, resp_json: dict) -> str:
#         # Prefer explicit assistant message paths used by Azure/OpenAI responses
#         try:
#             if not resp_json:
#                 return ''
#             # SDK path or simplified dict with 'text'
#             if isinstance(resp_json, dict) and 'text' in resp_json and isinstance(resp_json['text'], str):
#                 return resp_json['text']

#             # OpenAI/Azure style response: choices -> message -> content
#             if isinstance(resp_json, dict) and 'choices' in resp_json and isinstance(resp_json['choices'], list):
#                 for choice in resp_json['choices']:
#                     # choice may have 'message' dict
#                     if isinstance(choice, dict):
#                         msg = choice.get('message') or choice.get('content') or choice.get('text')
#                         if isinstance(msg, dict):
#                             content = msg.get('content') or msg.get('text')
#                             if isinstance(content, str) and content.strip():
#                                 return content
#                         if isinstance(msg, str) and msg.strip():
#                             return msg

#             # 'output' -> may contain structured blocks
#             if isinstance(resp_json, dict) and 'output' in resp_json:
#                 out = resp_json['output']
#                 if isinstance(out, str) and out.strip():
#                     return out
#                 if isinstance(out, list):
#                     for item in out:
#                         if isinstance(item, dict):
#                             # look for 'content' fields
#                             c = item.get('content') or item.get('text')
#                             if isinstance(c, str) and c.strip():
#                                 return c

#             # Fallback: shallow search but avoid returning filter 'severity' strings like 'safe'
#             def find_text(obj):
#                 if isinstance(obj, str):
#                     if obj.strip().lower() in ('safe', 'unsafe', 'filtered'):
#                         return None
#                     return obj
#                 if isinstance(obj, dict):
#                     for k, v in obj.items():
#                         if k.lower() in ('text', 'content', 'output') and isinstance(v, str):
#                             if v.strip().lower() in ('safe', 'unsafe', 'filtered'):
#                                 continue
#                             return v
#                     for v in obj.values():
#                         t = find_text(v)
#                         if t:
#                             return t
#                 if isinstance(obj, list):
#                     for v in obj:
#                         t = find_text(v)
#                         if t:
#                             return t
#                 return None

#             t = find_text(resp_json)
#             return t or ''
#         except Exception:
#             return ''

#     def _log_usage(self, resp_json: dict, prompt_text: str):
#         # Try to record token usage if provided by the provider; otherwise estimate roughly
#         usage = {}
#         if isinstance(resp_json, dict) and 'usage' in resp_json:
#             usage = resp_json.get('usage')
#         else:
#             # rough estimate: 4 chars ~ 1 token
#             out_text = self._extract_text_from_response(resp_json)
#             usage = {
#                 'estimated_prompt_tokens': max(1, int(len(prompt_text) / 4)),
#                 'estimated_completion_tokens': max(1, int(len(out_text) / 4)),
#             }

#         os.makedirs(os.path.join('app', 'logs'), exist_ok=True)
#         path = os.path.join('app', 'logs', 'token_usage.log')
#         entry = {'ts': int(time.time()), 'model': self.deployment, 'usage': usage}
#         try:
#             with open(path, 'a', encoding='utf-8') as fh:
#                 fh.write(json.dumps(entry) + "\n")
#         except Exception:
#             pass

#     def _azure_prompt_payload(self, prompt: str, temperature: float = 0.2, max_tokens: int = 1024) -> dict:
#         # Build the payload expected by Azure Chat Completions API
#         return {
#             'messages': [
#                 {'role': 'user', 'content': prompt}
#             ],
#             'max_tokens': max_tokens,
#             'temperature': temperature,
#         }

#     def call_llm(self, prompt: str, cache_ttl: int = 3600, trim_to: Optional[int] = None) -> str:
#         if trim_to:
#             prompt = self._trim_text(prompt, trim_to)

#         # cache key
#         key = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
#         cached = cache_get(key)
#         if cached:
#             return cached

#         payload = self._azure_prompt_payload(prompt)
#         try:
#             resp = self._call_azure_with_retry(payload)
#         except Exception as e:
#             self.last_error = str(e)
#             raise

#         # log token usage (or estimates)
#         try:
#             self._log_usage(resp, prompt)
#         except Exception:
#             pass

#         text = self._extract_text_from_response(resp)

#         # If extracted text looks like a content-filter verdict or is very short,
#         # log the raw provider response for debugging and avoid caching the sentinel.
#         short_or_sentinal = not text or (isinstance(text, str) and len(text.strip()) < 12)
#         if short_or_sentinal:
#             try:
#                 os.makedirs(os.path.join('app', 'logs'), exist_ok=True)
#                 logpath = os.path.join('app', 'logs', 'azure_raw_responses.log')
#                 entry = {'ts': int(time.time()), 'prompt_hash': key, 'raw': resp}
#                 with open(logpath, 'a', encoding='utf-8') as fh:
#                     fh.write(json.dumps(entry) + "\n")
#             except Exception:
#                 pass

#         # Only cache substantive outputs to avoid storing sentinels like 'safe'
#         try:
#             if isinstance(text, str) and len(text.strip()) >= 20:
#                 cache_set(key, text, ttl=cache_ttl)
#         except Exception:
#             pass

#         return text

#     def summarize_resume(self, resume_text: str, max_chars: int = 800) -> str:
#         prompt = (
#             "Summarize the following resume into a short professional summary (3-5 sentences) and list top skills as a comma-separated list. Return only plain text.\n\n" + resume_text
#         )
#         return self.call_llm(prompt, cache_ttl=24 * 3600, trim_to=max_chars)

#     def extract_skills_no_llm(self, resume_text: str) -> List[str]:
#         # Heuristic extraction: look for a Skills section or comma/line-separated skills
#         skills = []
#         try:
#             m = re.search(r"(?ims)skills[:\s]*\n(.{1,500})", resume_text)
#             block = None
#             if m:
#                 block = m.group(1)
#             else:
#                 # try to find 'Skills -' inline
#                 m2 = re.search(r"(?im)(Skills)[:\-]\s*(.*)", resume_text)
#                 if m2:
#                     block = m2.group(2)

#             if block:
#                 # split by commas or newlines
#                 parts = re.split(r'[\n,;|\\/]+', block)
#                 for p in parts:
#                     p = p.strip()
#                     if p and len(p) > 1:
#                         skills.append(p)
#         except Exception:
#             pass
#         # fallback: find frequent technology words
#         if not skills:
#             candidates = re.findall(r"\b(Python|JavaScript|Java|C\+\+|C#|SQL|AWS|GCP|Azure|TensorFlow|PyTorch|React|Django|Flask|Docker|Kubernetes)\b", resume_text, flags=re.I)
#             skills = list({c.strip() for c in candidates})
#         return [s.strip() for s in skills]

#     def match_skills(self, job_skills: List[str], resume_skills: List[str]) -> Tuple[List[str], List[str]]:
#         js = [s.lower() for s in (job_skills or [])]
#         rs = [s.lower() for s in (resume_skills or [])]
#         matched = [s for s in js if s in rs]
#         missing = [s for s in js if s not in rs]
#         return matched, missing
#     def _sanitize_text(self, text: str) -> str:
#         if not isinstance(text, str):
#             try:
#                 text = str(text)
#             except Exception:
#                 return ''
#         # Normalize whitespace and remove control characters
#         text = re.sub(r"\s+", " ", text).strip()
#         return text
#     def parse_resume(self, resume_text: str) -> dict:
#         """Parse resume text into structured JSON (name, contact, education, skills, experience).

#         Uses the Azure-backed `call_llm` helper and falls back to a simple heuristic if parsing fails.
#         """
#         prompt = (
#             "Parse the following resume text and return a JSON object with keys: name, contact, education, skills (list), experience (list of roles with dates), summary."
#             "\n\nRESUME TEXT:\n" + resume_text + "\n\nReturn only valid JSON."
#         )

#         try:
#             resp_text = self.call_llm(prompt, cache_ttl=3600, trim_to=3000)
#         except Exception as e:
#             self.last_error = str(e)
#             # fallback heuristic
#             try:
#                 from .resume_parser import extract_basic_resume_info
#                 return extract_basic_resume_info(resume_text)
#             except Exception:
#                 return {"name": None, "contact": {}, "education": [], "skills": [], "experience": [], "summary": None}

#         # try to parse JSON
#         try:
#             parsed = json.loads(resp_text)
#             return parsed
#         except Exception:
#             # fallback: return heuristic extraction
#             try:
#                 from .resume_parser import extract_basic_resume_info
#                 return extract_basic_resume_info(resume_text)
#             except Exception:
#                 return {"name": None, "contact": {}, "education": [], "skills": [], "experience": [], "summary": None}

#     def extract_job_poster(self, job_page_text: str):
#         prompt = (
#             "From the job page text below, extract any hiring contact or poster information and return a JSON object with keys: posted_on, poster_name, poster_link, poster_profile, contact_email. If not present, use null. Return only valid JSON.\n\n" + job_page_text
#         )
#         try:
#             resp = self.call_llm(prompt, cache_ttl=3600, trim_to=1500)
#         except Exception as e:
#             self.last_error = str(e)
#             return {"posted_on": None, "poster_name": None, "poster_link": None, "poster_profile": None, "contact_email": None}

#         try:
#             parsed = json.loads(resp)
#         except Exception:
#             # best-effort: try to regex an email
#             m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", job_page_text)
#             return {"posted_on": None, "poster_name": None, "poster_link": None, "poster_profile": None, "contact_email": m.group(0) if m else None}
#         return parsed

#     def extract_jobs(self, page_text: str):
#         """Extract one or more job entries from a job page text and return a list of job dicts.

#         Each job dict should contain at least: `role`, `location`, `skills` (list), `description`.
#         """
#         prompt_extract = (
#             "From the job page text below, extract one or more job postings. For each posting return a JSON object with keys: role, location, skills (list), description (full text). Return a JSON array only.\n\n" + page_text
#         )

#         try:
#             res_text = self.call_llm(prompt_extract, cache_ttl=3600, trim_to=3000)
#         except Exception as e:
#             self.last_error = e
#             msg_low = str(e).lower()
#             # If request is too large, fall back to a lightweight heuristic extraction
#             if 'request_too_large' in msg_low or 'request entity too large' in msg_low or '413' in msg_low:
#                 # simple heuristic: try to extract role/location using common page elements
#                 try:
#                     import re
#                     role = None
#                     location = None
#                     m_role = re.search(r"(?im)^(?:Job\s*Title|Title)\s*[:\-]\s*(.+)$", page_text)
#                     if m_role:
#                         role = m_role.group(1).strip()
#                     m_loc = re.search(r"(?im)^Location\s*[:\-]\s*(.+)$", page_text)
#                     if m_loc:
#                         location = m_loc.group(1).strip()
#                     # fallback to <title> or <h1>
#                     if not role:
#                         m_title = re.search(r"<title\s*>([^<]+)</title>", page_text, flags=re.I)
#                         if m_title:
#                             role = m_title.group(1).strip()
#                     if not role:
#                         m_h1 = re.search(r"<h1[^>]*>([^<]+)</h1>", page_text, flags=re.I)
#                         if m_h1:
#                             role = m_h1.group(1).strip()
#                     # try meta location
#                     if not location:
#                         m_meta_loc = re.search(r"<meta[^>]+name=[\'\"]?location[\'\"]?[^>]+content=[\'\"]([^\'\"]+)[\'\"]", page_text, flags=re.I)
#                         if m_meta_loc:
#                             location = m_meta_loc.group(1).strip()
#                     return [{"role": role, "location": location, "skills": [], "description": page_text}]
#                 except Exception:
#                     return [{"role": None, "location": None, "skills": [], "description": page_text}]
#             else:
#                 if 'model_not_found' in msg_low or 'does not exist' in msg_low or 'decommission' in msg_low:
#                     self.last_error = msg_low
#                     raise
#                 else:
#                     raise

#         try:
#             parsed = json.loads(res_text)
#         except Exception:
#             self.last_error = 'Output parsing failed for job extraction'
#             return [{"role": None, "location": None, "skills": [], "description": page_text}]

#         return parsed if isinstance(parsed, list) else [parsed]

#     def write_mail_with_resume(self, job, resume_info, missing_requirements=None):
#         # Use the provided concise email template. Keep token usage low by providing resume summary if available.
#         resume_summary = resume_info.get('summary') if isinstance(resume_info, dict) else None
#         if not resume_summary:
#             try:
#                 resume_summary = self.summarize_resume(json.dumps(resume_info) if isinstance(resume_info, dict) else str(resume_info))
#             except Exception:
#                 resume_summary = ''

#         # Build a structured prompt asking the model to return JSON with specific fields.
#         job_json = json.dumps(job) if isinstance(job, dict) else str(job)
#         prompt = (
#             f"You are a hiring-focused AI assistant specialized in crafting high-conversion job application emails.\n\n"
#             f"Candidate Resume Summary:\n{resume_summary}\n\n"
#             f"Job Description:\n{job_json}\n\n"
#             "Task: Generate a personalized job application email that is ready-to-send without further edits.\n"
#             "Instructions:\n"
#             "1) Return ONLY valid JSON (no surrounding text).\n"
#             "2) JSON keys: subject (string), body (string), ready_to_send (true/false), notes (string explaining any anomalies), role_exact (the role string exactly as found in the job description), job_url (string).\n"
#             "3) Fill placeholders: if any placeholders like [Your Name] or [Company Name] appear, replace them using the resume data if available.\n"
#             "4) Keep the body concise (120-170 words) and include top 3 matching skills.\n"
#             "5) Ensure the subject line includes the role and location if present.\n"
#             "6) If you cannot confidently fill a field, set ready_to_send to false and explain why in notes.\n"
#             "Provide the JSON now."
#         )

#         try:
#             out = self.call_llm(prompt, cache_ttl=3600, trim_to=1200)
#         except Exception as e:
#             self.last_error = str(e)
#             raise

#         # Try to parse the model's JSON output. If the model returned text containing
#         # a JSON object (wrapped in additional commentary), attempt to extract and parse
#         # the first balanced JSON object before falling back to wrapping the raw text.
#         mail_obj = None
#         try:
#             mail_obj = json.loads(out)
#         except Exception:
#             text = out or ''

#             def _extract_first_json(s: str):
#                 start = s.find('{')
#                 if start == -1:
#                     return None
#                 stack = 0
#                 for i in range(start, len(s)):
#                     ch = s[i]
#                     if ch == '{':
#                         stack += 1
#                     elif ch == '}':
#                         stack -= 1
#                         if stack == 0:
#                             return s[start:i+1]
#                 return None

#             blob = _extract_first_json(text)
#             if blob:
#                 try:
#                     mail_obj = json.loads(blob)
#                 except Exception:
#                     mail_obj = None

#             if not mail_obj:
#                 # Build a fallback JSON structure wrapping the raw output
#                 mail_obj = {
#                     'subject': (f"Application for {job.get('role')}") if isinstance(job, dict) else 'Application',
#                     'body': text,
#                     'ready_to_send': True if text and '[Your' not in text else False,
#                     'notes': 'Provider did not return JSON; wrapped raw output.',
#                     'role_exact': job.get('role') if isinstance(job, dict) else None,
#                     'job_url': job.get('source_url') if isinstance(job, dict) else None,
#                 }

#         # If the provider returned raw text that includes a leading 'Subject:' line,
#         # try to extract the subject and body into the structured fields.
#         try:
#             if isinstance(mail_obj.get('body'), str):
#                 body_text = mail_obj['body']
#                 msub = re.search(r"(?ims)^\s*Subject\s*:\s*(.+?)(?:\n\s*\n|\n)", body_text)
#                 if msub:
#                     subj = msub.group(1).strip()
#                     rest = body_text[msub.end():].strip()
#                     mail_obj['subject'] = subj
#                     mail_obj['body'] = rest
#         except Exception:
#             pass

#         # Auto-fill common placeholders using resume_info
#         def _fill_placeholders(s: str) -> str:
#             if not isinstance(s, str):
#                 return s
#             name = resume_info.get('name') if isinstance(resume_info, dict) else None
#             contact = resume_info.get('contact') if isinstance(resume_info, dict) else None
#             linkedin = None
#             if contact and isinstance(contact, dict):
#                 linkedin = contact.get('linkedin') or contact.get('profile')
#             replacements = {
#                 '[Your Full Name]': name or '',
#                 '[Your Name]': name or '',
#                 '[Your Contact Information]': ', '.join(filter(None, [
#                     (contact.get('email') if isinstance(contact, dict) else None),
#                     (contact.get('phone') if isinstance(contact, dict) else None)
#                 ])) if contact else '',
#                 '[Your LinkedIn Profile]': linkedin or '',
#                 '[Company Name]': job.get('company') if isinstance(job, dict) else '',
#                 '[Job Title]': job.get('role') if isinstance(job, dict) else '',
#             }
#             # Accept common alternate placeholder variants
#             alt_map = {
#                 '[Candidate Name]': name or '',
#                 '[Email]': (contact.get('email') if isinstance(contact, dict) else '') or '',
#                 '[Phone]': (contact.get('phone') if isinstance(contact, dict) else '') or '',
#                 '[Your Email]': (contact.get('email') if isinstance(contact, dict) else '') or '',
#                 '[Your Phone]': (contact.get('phone') if isinstance(contact, dict) else '') or '',
#                 '[your email]': (contact.get('email') if isinstance(contact, dict) else '') or '',
#                 '[your phone]': (contact.get('phone') if isinstance(contact, dict) else '') or '',
#                 '[Contact]': ', '.join(filter(None, [contact.get('email') if isinstance(contact, dict) else None, contact.get('phone') if isinstance(contact, dict) else None])) if contact else '',
#                 '[Contact Information]': ', '.join(filter(None, [contact.get('email') if isinstance(contact, dict) else None, contact.get('phone') if isinstance(contact, dict) else None])) if contact else '',
#             }
#             replacements.update(alt_map)
#             for k, v in replacements.items():
#                 if v:
#                     s = s.replace(k, v)
#             return s

#         try:
#             mail_obj['subject'] = _fill_placeholders(mail_obj.get('subject') or '')
#             mail_obj['body'] = _fill_placeholders(mail_obj.get('body') or '')
#             # Ensure role_exact and job_url fields exist
#             if 'role_exact' not in mail_obj:
#                 mail_obj['role_exact'] = job.get('role') if isinstance(job, dict) else None
#             if 'job_url' not in mail_obj:
#                 mail_obj['job_url'] = job.get('source_url') if isinstance(job, dict) else None

#             # Validate for remaining placeholders
#             placeholders = ['[Your', '[Company', '[Job Title', '[Your Contact']
#             if any(p in (mail_obj.get('subject','') + mail_obj.get('body','')) for p in placeholders):
#                 # try a second pass: if resume_info has more fields, replace common variants
#                 mail_obj['body'] = _fill_placeholders(mail_obj['body'])
#                 mail_obj['subject'] = _fill_placeholders(mail_obj['subject'])

#             # Final ready_to_send: ensure required contact info is present
#             if not mail_obj.get('ready_to_send'):
#                 # If body/subject contains no obvious placeholders and resume has contact info, set ready
#                 has_contact = False
#                 if isinstance(resume_info, dict) and isinstance(resume_info.get('contact'), dict):
#                     c = resume_info['contact']
#                     if c.get('email') or c.get('phone'):
#                         has_contact = True
#                 if has_contact and ('[Your' not in (mail_obj.get('body') + mail_obj.get('subject'))):
#                     mail_obj['ready_to_send'] = True

#             # sanitize text fields
#             mail_obj['subject'] = self._sanitize_text(mail_obj.get('subject') or '')
#             mail_obj['body'] = self._sanitize_text(mail_obj.get('body') or '')
#             mail_obj['notes'] = self._sanitize_text(mail_obj.get('notes') or '')
#         except Exception:
#             pass

#         return mail_obj

#     def write_mail(self, job, links):
#         prompt_email = (
#             f"You are Mohan, a business development executive at AtliQ. Write a concise cold email (no preamble) pitching AtliQ's capability to meet the needs in the job description below.\n\n"
#             f"Job Description:\n{json.dumps(job) if isinstance(job, dict) else str(job)}\n\n"
#             f"Include the most relevant portfolio links: {links}\n\nOutput: Subject line and Email body only."
#         )
#         out = self.call_llm(prompt_email, cache_ttl=3600, trim_to=800)
#         return self._sanitize_text(out)

#     @staticmethod
#     def probe_model(groq_api_key: str, model_name: str, timeout_seconds: int = 10) -> dict:
#         """Try to instantiate a small ChatGroq and run a tiny prompt to check availability.

#         Returns dict: {"ok": bool, "model": model_name, "error": str or None}
#         """
#         from langchain_groq import ChatGroq
#         from langchain_core.prompts import PromptTemplate
#         try:
#             test_llm = ChatGroq(temperature=0, groq_api_key=groq_api_key, model_name=model_name)
#         except Exception as e:
#             return {"ok": False, "model": model_name, "error": str(e)}

#         try:
#             prompt = PromptTemplate.from_template("Say OK as a single word.")
#             chain = prompt | test_llm
#             res = chain.invoke({})
#             return {"ok": True, "model": model_name, "error": None, "response_preview": getattr(res, 'content', str(res))}
#         except Exception as e:
#             return {"ok": False, "model": model_name, "error": str(e)}


# if __name__ == "__main__":
#     print(os.getenv("GROQ_API_KEY"))


"""
chains.py — Azure-backed LLM chain for the Email Generator pipeline.

Responsibilities:
- Wrap Azure OpenAI Chat Completions with retry / back-off logic
- Cache responses to avoid redundant API calls
- Provide domain helpers: resume parsing, job extraction, email generation
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from .cache import get as cache_get, set as cache_set

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional Azure AI Projects SDK
# ---------------------------------------------------------------------------
_HAS_AZURE_PROJECTS = False
AIProjectClient = None
AzureKeyCredential = None
DefaultAzureCredential = None

try:
    from azure.ai.projects import AIProjectClient          # type: ignore
    from azure.core.credentials import AzureKeyCredential  # type: ignore
    from azure.identity import DefaultAzureCredential      # type: ignore
    _HAS_AZURE_PROJECTS = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_DEPLOYMENT = "gpt-35-turbo"
DEFAULT_API_VERSION = "2024-02-15-preview"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 1024
DEFAULT_CACHE_TTL = 3600
DEFAULT_TRIM_CHARS = 2000
MIN_CACHEABLE_LEN = 20          # characters — avoid caching filter sentinels
SENTINEL_WORDS = {"safe", "unsafe", "filtered"}
RETRY_STATUS_CODES = {429, 502, 503, 504}
MAX_RETRIES = 3
BACKOFF_BASE = 2.0              # seconds
REQUEST_TIMEOUT = 30            # seconds

COMMON_TECH_SKILLS = (
    "Python", "JavaScript", "Java", "C\\+\\+", "C#", "SQL",
    "AWS", "GCP", "Azure", "TensorFlow", "PyTorch", "React",
    "Django", "Flask", "Docker", "Kubernetes",
)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class AzureChainError(RuntimeError):
    """Raised when the Azure backend returns an unrecoverable error."""


class ConfigurationError(AzureChainError):
    """Raised when required environment variables are missing."""


# ---------------------------------------------------------------------------
# Dataclasses for structured return values
# ---------------------------------------------------------------------------

@dataclass
class ResumeInfo:
    name: Optional[str] = None
    contact: Dict[str, str] = field(default_factory=dict)
    education: List[Dict] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    experience: List[Dict] = field(default_factory=list)
    summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "contact": self.contact,
            "education": self.education,
            "skills": self.skills,
            "experience": self.experience,
            "summary": self.summary,
        }

    @classmethod
    def empty(cls) -> "ResumeInfo":
        return cls()


@dataclass
class JobPoster:
    posted_on: Optional[str] = None
    poster_name: Optional[str] = None
    poster_link: Optional[str] = None
    poster_profile: Optional[str] = None
    contact_email: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "posted_on": self.posted_on,
            "poster_name": self.poster_name,
            "poster_link": self.poster_link,
            "poster_profile": self.poster_profile,
            "contact_email": self.contact_email,
        }

    @classmethod
    def empty(cls) -> "JobPoster":
        return cls()


@dataclass
class MailResult:
    subject: str = ""
    body: str = ""
    ready_to_send: bool = False
    notes: str = ""
    role_exact: Optional[str] = None
    job_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subject": self.subject,
            "body": self.body,
            "ready_to_send": self.ready_to_send,
            "notes": self.notes,
            "role_exact": self.role_exact,
            "job_url": self.job_url,
        }


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------

class Chain:
    """Azure-backed LLM chain with retry, caching, and domain helpers.

    Parameters
    ----------
    azure_api_key : str, optional
        Azure OpenAI API key. Falls back to ``AZURE_OPENAI_API_KEY`` env var.
    endpoint : str, optional
        Azure OpenAI resource endpoint. Falls back to ``AZURE_OPENAI_ENDPOINT``.
    deployment : str, optional
        Model deployment name. Falls back to ``AZURE_OPENAI_DEPLOYMENT`` or
        ``'gpt-35-turbo'``.
    """

    def __init__(
        self,
        azure_api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        deployment: Optional[str] = None,
    ) -> None:
        self.azure_key: str = azure_api_key or os.getenv("AZURE_OPENAI_API_KEY", "")
        self.endpoint: str = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT", "")
        self.deployment: str = (
            deployment
            or os.getenv("AZURE_OPENAI_DEPLOYMENT")
            or DEFAULT_DEPLOYMENT
        )

        if not self.azure_key or not self.endpoint:
            raise ConfigurationError(
                "Azure endpoint or key not configured. "
                "Set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT."
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_text(text: Any) -> str:
        """Normalise whitespace and coerce to str. Returns '' on failure."""
        try:
            if not isinstance(text, str):
                text = str(text)
            return re.sub(r"\s+", " ", text).strip()
        except Exception:
            return ""

    @staticmethod
    def _trim_text(text: str, max_chars: int = DEFAULT_TRIM_CHARS) -> str:
        """Trim *text* to at most *max_chars*, preferring sentence boundaries."""
        if not text:
            return ""
        text = text.strip()
        if len(text) <= max_chars:
            return text
        cut = text[:max_chars]
        match = re.search(r"([.!?]\s)[^.!?]*$", cut)
        if match:
            return cut[: match.start() + 1]
        return cut

    def _build_target_url(self) -> Optional[str]:
        """Return the REST URL to call, or *None* if the SDK path should be used."""
        parsed = urlparse(self.endpoint)
        base = f"{parsed.scheme}://{parsed.netloc}"

        if "/api/projects/" in self.endpoint:
            # Studio project endpoint — handled by the Azure SDK
            return None
        if "/openai/deployments/" in self.endpoint:
            # Fully-qualified URL already provided
            return self.endpoint
        # Standard resource endpoint — build the Chat Completions URL
        return (
            f"{base}/openai/deployments/{self.deployment}"
            f"/chat/completions?api-version={DEFAULT_API_VERSION}"
        )

    def _call_via_sdk(self, payload: dict) -> Optional[dict]:
        """Attempt to call Azure AI Projects SDK. Returns response dict or None."""
        if not (_HAS_AZURE_PROJECTS and AIProjectClient):
            return None
        try:
            cred = (
                AzureKeyCredential(self.azure_key)
                if (AzureKeyCredential and self.azure_key)
                else DefaultAzureCredential()
            )
            proj_client = AIProjectClient(endpoint=self.endpoint, credential=cred)
            openai_client = proj_client.get_openai_client()

            sdk_input = payload.get("messages") or [
                {"role": "user", "content": str(payload.get("input", ""))}
            ]
            resp = openai_client.responses.create(input=sdk_input)
            text = (
                getattr(resp, "output_text", None)
                or (json.dumps(resp.output) if getattr(resp, "output", None) else None)
                or str(resp)
            )
            return {"text": text}
        except Exception as exc:
            logger.warning("Azure SDK call failed, falling back to HTTP: %s", exc)
            return None

    def _call_azure_with_retry(
        self,
        payload: dict,
        retries: int = MAX_RETRIES,
        backoff_base: float = BACKOFF_BASE,
    ) -> dict:
        """POST *payload* to Azure with exponential back-off retry.

        Tries the SDK path first for Studio project endpoints, then falls
        back to plain HTTP.
        """
        target_url = self._build_target_url()

        # SDK path (Studio project endpoints)
        if target_url is None:
            sdk_result = self._call_via_sdk(payload)
            if sdk_result is not None:
                return sdk_result
            # SDK failed — fall back to raw endpoint
            target_url = self.endpoint

        headers = {
            "api-key": self.azure_key,
            "Content-Type": "application/json",
        }

        for attempt in range(1, retries + 2):
            try:
                resp = requests.post(
                    target_url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
                )
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        return {"text": resp.text}

                if resp.status_code in RETRY_STATUS_CODES or resp.status_code >= 500:
                    if attempt > retries:
                        logger.error(
                            "Azure returned %s after %d retries: %s",
                            resp.status_code, retries, resp.text[:300],
                        )
                        resp.raise_for_status()
                    wait = backoff_base * attempt
                    logger.warning(
                        "Azure %s — retry %d/%d in %.1fs",
                        resp.status_code, attempt, retries, wait,
                    )
                    time.sleep(wait)
                    continue

                # Non-retryable client error
                resp.raise_for_status()

            except requests.RequestException as exc:
                if attempt > retries:
                    raise AzureChainError(f"Request failed after {retries} retries: {exc}") from exc
                wait = backoff_base * attempt
                logger.warning("Network error — retry %d/%d in %.1fs: %s", attempt, retries, wait, exc)
                time.sleep(wait)

        # Should be unreachable, but satisfies type checkers
        raise AzureChainError("Exhausted retries without a response.")

    def _extract_text_from_response(self, resp_json: dict) -> str:
        """Extract the assistant's text from various Azure/OpenAI response shapes."""
        if not resp_json or not isinstance(resp_json, dict):
            return ""

        # Simplified dict from SDK path
        if isinstance(resp_json.get("text"), str):
            return resp_json["text"]

        # Standard Chat Completions: choices[].message.content
        for choice in resp_json.get("choices", []):
            if not isinstance(choice, dict):
                continue
            msg = choice.get("message") or choice.get("content") or choice.get("text")
            if isinstance(msg, dict):
                content = msg.get("content") or msg.get("text", "")
                if isinstance(content, str) and content.strip():
                    return content
            if isinstance(msg, str) and msg.strip():
                return msg

        # Responses API / structured output block
        output = resp_json.get("output")
        if isinstance(output, str) and output.strip():
            return output
        if isinstance(output, list):
            for item in output:
                if isinstance(item, dict):
                    candidate = item.get("content") or item.get("text", "")
                    if isinstance(candidate, str) and candidate.strip():
                        return candidate

        # Generic recursive search — skip content-filter sentinels
        return self._deep_find_text(resp_json) or ""

    @staticmethod
    def _deep_find_text(obj: Any) -> Optional[str]:
        """Recursively hunt for a non-sentinel text value."""
        if isinstance(obj, str):
            return None if obj.strip().lower() in SENTINEL_WORDS else obj
        if isinstance(obj, dict):
            for key in ("text", "content", "output"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip().lower() not in SENTINEL_WORDS:
                    return val
            for val in obj.values():
                found = Chain._deep_find_text(val)
                if found:
                    return found
        if isinstance(obj, list):
            for item in obj:
                found = Chain._deep_find_text(item)
                if found:
                    return found
        return None

    def _log_token_usage(self, resp_json: dict, prompt_text: str) -> None:
        """Append token-usage data to *app/logs/token_usage.log*."""
        usage = resp_json.get("usage") if isinstance(resp_json, dict) else None
        if not usage:
            out_text = self._extract_text_from_response(resp_json)
            usage = {
                "estimated_prompt_tokens": max(1, len(prompt_text) // 4),
                "estimated_completion_tokens": max(1, len(out_text) // 4),
            }
        log_dir = os.path.join("app", "logs")
        os.makedirs(log_dir, exist_ok=True)
        entry = json.dumps({"ts": int(time.time()), "model": self.deployment, "usage": usage})
        try:
            with open(os.path.join(log_dir, "token_usage.log"), "a", encoding="utf-8") as fh:
                fh.write(entry + "\n")
        except OSError as exc:
            logger.warning("Could not write token_usage.log: %s", exc)

    def _log_raw_response(self, prompt_key: str, resp: dict) -> None:
        """Log raw Azure responses that contain suspiciously short/sentinel text."""
        log_dir = os.path.join("app", "logs")
        os.makedirs(log_dir, exist_ok=True)
        entry = json.dumps({"ts": int(time.time()), "prompt_hash": prompt_key, "raw": resp})
        try:
            with open(os.path.join(log_dir, "azure_raw_responses.log"), "a", encoding="utf-8") as fh:
                fh.write(entry + "\n")
        except OSError as exc:
            logger.warning("Could not write azure_raw_responses.log: %s", exc)

    @staticmethod
    def _build_chat_payload(
        prompt: str,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict:
        return {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

    @staticmethod
    def _parse_json_response(text: str) -> Optional[dict]:
        """Try to parse *text* as JSON, extracting the first balanced ``{…}`` if needed."""
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Extract first complete JSON object
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start: i + 1])
                    except json.JSONDecodeError:
                        return None
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def call_llm(
        self,
        prompt: str,
        cache_ttl: int = DEFAULT_CACHE_TTL,
        trim_to: Optional[int] = None,
    ) -> str:
        """Send *prompt* to Azure OpenAI and return the text response.

        Results are cached by SHA-256 of the prompt. Sentinel/filter
        responses are never cached.

        Parameters
        ----------
        prompt : str
            The user prompt to send.
        cache_ttl : int
            Cache time-to-live in seconds (default 3600).
        trim_to : int, optional
            Trim the prompt to this many characters before sending.
        """
        if trim_to:
            prompt = self._trim_text(prompt, trim_to)

        cache_key = hashlib.sha256(prompt.encode()).hexdigest()
        cached = cache_get(cache_key)
        if cached:
            return cached

        payload = self._build_chat_payload(prompt)
        resp = self._call_azure_with_retry(payload)

        try:
            self._log_token_usage(resp, prompt)
        except Exception as exc:
            logger.debug("Token usage logging failed: %s", exc)

        text = self._extract_text_from_response(resp)

        if not text or len(text.strip()) < MIN_CACHEABLE_LEN:
            logger.warning("Suspiciously short response (len=%d); logging raw.", len(text or ""))
            try:
                self._log_raw_response(cache_key, resp)
            except Exception:
                pass
        else:
            try:
                cache_set(cache_key, text, ttl=cache_ttl)
            except Exception as exc:
                logger.debug("Cache write failed: %s", exc)

        return text

    # ------------------------------------------------------------------
    # Domain helpers
    # ------------------------------------------------------------------

    def summarize_resume(self, resume_text: str, max_chars: int = 800) -> str:
        """Return a 3-5 sentence professional summary and top skills for *resume_text*."""
        prompt = (
            "Summarize the following resume into a short professional summary "
            "(3-5 sentences) and list top skills as a comma-separated list. "
            "Return only plain text.\n\n" + resume_text
        )
        return self.call_llm(prompt, cache_ttl=24 * DEFAULT_CACHE_TTL, trim_to=max_chars)

    def extract_skills_no_llm(self, resume_text: str) -> List[str]:
        """Heuristically extract skills from *resume_text* without an LLM call."""
        block: Optional[str] = None
        match = re.search(r"(?ims)skills[:\s]*\n(.{1,500})", resume_text)
        if match:
            block = match.group(1)
        else:
            inline = re.search(r"(?im)Skills[:\-]\s*(.*)", resume_text)
            if inline:
                block = inline.group(2)

        skills: List[str] = []
        if block:
            skills = [
                p.strip()
                for p in re.split(r"[\n,;|/\\]+", block)
                if p.strip() and len(p.strip()) > 1
            ]

        if not skills:
            pattern = r"\b(" + "|".join(COMMON_TECH_SKILLS) + r")\b"
            skills = list({c.strip() for c in re.findall(pattern, resume_text, re.I)})

        return skills

    def match_skills(
        self, job_skills: List[str], resume_skills: List[str]
    ) -> Tuple[List[str], List[str]]:
        """Return *(matched, missing)* skill lists comparing job vs resume skills."""
        job_lower = {s.lower() for s in (job_skills or [])}
        resume_lower = {s.lower() for s in (resume_skills or [])}
        matched = sorted(job_lower & resume_lower)
        missing = sorted(job_lower - resume_lower)
        return matched, missing

    def parse_resume(self, resume_text: str) -> Dict[str, Any]:
        """Parse *resume_text* into a structured dict via LLM, with heuristic fallback.

        Returns keys: name, contact, education, skills, experience, summary.
        """
        prompt = (
            "Parse the following resume text and return a JSON object with keys: "
            "name, contact, education, skills (list), experience (list of roles with dates), summary."
            "\n\nRESUME TEXT:\n" + resume_text + "\n\nReturn only valid JSON."
        )
        try:
            resp_text = self.call_llm(prompt, cache_ttl=DEFAULT_CACHE_TTL, trim_to=3000)
            parsed = self._parse_json_response(resp_text)
            if parsed and isinstance(parsed, dict):
                return parsed
        except Exception as exc:
            logger.warning("LLM resume parse failed: %s", exc)

        return self._fallback_resume_parse(resume_text)

    def _fallback_resume_parse(self, resume_text: str) -> Dict[str, Any]:
        try:
            from .resume_parser import extract_basic_resume_info  # type: ignore
            return extract_basic_resume_info(resume_text)
        except Exception as exc:
            logger.warning("Heuristic resume parse also failed: %s", exc)
            return ResumeInfo.empty().to_dict()

    def extract_job_poster(self, job_page_text: str) -> Dict[str, Any]:
        """Extract hiring contact / poster information from *job_page_text*."""
        prompt = (
            "From the job page text below, extract any hiring contact or poster information "
            "and return a JSON object with keys: posted_on, poster_name, poster_link, "
            "poster_profile, contact_email. If not present, use null. Return only valid JSON.\n\n"
            + job_page_text
        )
        try:
            resp = self.call_llm(prompt, cache_ttl=DEFAULT_CACHE_TTL, trim_to=1500)
            parsed = self._parse_json_response(resp)
            if parsed and isinstance(parsed, dict):
                return parsed
        except Exception as exc:
            logger.warning("extract_job_poster LLM failed: %s", exc)

        # Regex fallback for email
        email_match = re.search(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", job_page_text
        )
        return JobPoster(
            contact_email=email_match.group(0) if email_match else None
        ).to_dict()

    def extract_jobs(self, page_text: str) -> List[Dict[str, Any]]:
        """Extract one or more job postings from *page_text*.

        Returns a list of dicts with keys: role, location, skills, description.
        Falls back to lightweight heuristic extraction on context-length errors.
        """
        prompt = (
            "From the job page text below, extract one or more job postings. "
            "For each posting return a JSON object with keys: role, location, "
            "skills (list), description (full text). Return a JSON array only.\n\n"
            + page_text
        )
        try:
            res_text = self.call_llm(prompt, cache_ttl=DEFAULT_CACHE_TTL, trim_to=3000)
        except AzureChainError as exc:
            msg = str(exc).lower()
            if any(k in msg for k in ("request_too_large", "request entity too large", "413")):
                logger.warning("Payload too large for extract_jobs; using heuristic fallback.")
                return [self._heuristic_job_extract(page_text)]
            if any(k in msg for k in ("model_not_found", "does not exist", "decommission")):
                logger.error("Deployment unavailable: %s", exc)
                raise
            raise

        parsed = self._parse_json_response(res_text)
        if parsed is None:
            logger.warning("extract_jobs: JSON parse failed; returning raw text fallback.")
            return [{"role": None, "location": None, "skills": [], "description": page_text}]
        return parsed if isinstance(parsed, list) else [parsed]

    @staticmethod
    def _heuristic_job_extract(page_text: str) -> Dict[str, Any]:
        """Best-effort job extraction using regex when the LLM cannot handle the payload."""
        role: Optional[str] = None
        location: Optional[str] = None

        for pattern in (
            r"(?im)^(?:Job\s*Title|Title)\s*[:\-]\s*(.+)$",
            r"<title\s*>([^<]+)</title>",
            r"<h1[^>]*>([^<]+)</h1>",
        ):
            m = re.search(pattern, page_text, re.I)
            if m:
                role = m.group(1).strip()
                break

        for pattern in (
            r"(?im)^Location\s*[:\-]\s*(.+)$",
            r'<meta[^>]+name=[\'"]?location[\'"]?[^>]+content=[\'"]([^\'"]+)[\'"]',
        ):
            m = re.search(pattern, page_text, re.I)
            if m:
                location = m.group(1).strip()
                break

        return {"role": role, "location": location, "skills": [], "description": page_text}

    # ------------------------------------------------------------------
    # Email generation
    # ------------------------------------------------------------------

    def write_mail_with_resume(
        self,
        job: Dict[str, Any],
        resume_info: Dict[str, Any],
        missing_requirements: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generate a ready-to-send job-application email.

        Parameters
        ----------
        job : dict
            Job info dict (role, location, skills, description, source_url, company …).
        resume_info : dict
            Parsed resume dict (name, contact, skills, summary …).
        missing_requirements : list[str], optional
            Skills the candidate lacks (informational only).

        Returns
        -------
        dict
            Keys: subject, body, ready_to_send, notes, role_exact, job_url.
        """
        resume_summary = (
            resume_info.get("summary")
            if isinstance(resume_info, dict)
            else None
        )
        if not resume_summary:
            try:
                raw = json.dumps(resume_info) if isinstance(resume_info, dict) else str(resume_info)
                resume_summary = self.summarize_resume(raw)
            except Exception as exc:
                logger.warning("summarize_resume failed: %s", exc)
                resume_summary = ""

        prompt = (
            "You are a hiring-focused AI assistant specialized in crafting high-conversion job application emails.\n\n"
            f"Candidate Resume Summary:\n{resume_summary}\n\n"
            f"Job Description:\n{json.dumps(job) if isinstance(job, dict) else str(job)}\n\n"
            "Task: Generate a personalized job application email that is ready-to-send without further edits.\n"
            "Instructions:\n"
            "1) Return ONLY valid JSON (no surrounding text).\n"
            "2) JSON keys: subject (string), body (string), ready_to_send (true/false), "
            "notes (string explaining any anomalies), role_exact (the role string exactly as found "
            "in the job description), job_url (string).\n"
            "3) Replace any placeholders like [Your Name] or [Company Name] using resume data if available.\n"
            "4) Keep the body concise (120-170 words) and include top 3 matching skills.\n"
            "5) Include the role and location in the subject line if present.\n"
            "6) If you cannot confidently fill a field, set ready_to_send to false and explain in notes.\n"
            "Provide the JSON now."
        )

        out = self.call_llm(prompt, cache_ttl=DEFAULT_CACHE_TTL, trim_to=1200)
        mail = self._parse_json_response(out)

        if mail is None:
            mail = {
                "subject": f"Application for {job.get('role', '')}" if isinstance(job, dict) else "Application",
                "body": out,
                "ready_to_send": bool(out and "[Your" not in out),
                "notes": "Provider did not return JSON; wrapped raw output.",
                "role_exact": job.get("role") if isinstance(job, dict) else None,
                "job_url": job.get("source_url") if isinstance(job, dict) else None,
            }

        # Promote Subject: line from body if the model embedded it there
        self._hoist_subject_from_body(mail)

        # Fill common placeholder tokens from resume data
        filler = PlaceholderFiller(job, resume_info)
        mail["subject"] = filler.fill(mail.get("subject", ""))
        mail["body"] = filler.fill(mail.get("body", ""))

        # Ensure required keys exist
        mail.setdefault("role_exact", job.get("role") if isinstance(job, dict) else None)
        mail.setdefault("job_url", job.get("source_url") if isinstance(job, dict) else None)

        # Re-evaluate ready_to_send based on remaining placeholders and contact info
        self._resolve_ready_to_send(mail, resume_info)

        # Final sanitisation
        for key in ("subject", "body", "notes"):
            mail[key] = self._sanitize_text(mail.get(key, ""))

        return mail

    @staticmethod
    def _hoist_subject_from_body(mail: dict) -> None:
        """If the body starts with ``Subject: …``, move it to the subject field."""
        body = mail.get("body", "")
        m = re.search(r"(?ims)^\s*Subject\s*:\s*(.+?)(?:\n\s*\n|\n)", body)
        if m:
            mail["subject"] = m.group(1).strip()
            mail["body"] = body[m.end():].strip()

    @staticmethod
    def _resolve_ready_to_send(mail: dict, resume_info: Dict[str, Any]) -> None:
        """Set ready_to_send=True when contact info is present and no placeholders remain."""
        combined = (mail.get("subject", "") + mail.get("body", ""))
        has_placeholder = "[Your" in combined or "[Company" in combined
        has_contact = False
        if isinstance(resume_info, dict) and isinstance(resume_info.get("contact"), dict):
            c = resume_info["contact"]
            has_contact = bool(c.get("email") or c.get("phone"))
        mail["ready_to_send"] = has_contact and not has_placeholder

    def write_mail(self, job: Dict[str, Any], links: Any) -> str:
        """Write a cold business-development email for AtliQ targeting *job*."""
        prompt = (
            "You are Mohan, a business development executive at AtliQ. "
            "Write a concise cold email (no preamble) pitching AtliQ's capability "
            "to meet the needs in the job description below.\n\n"
            f"Job Description:\n{json.dumps(job) if isinstance(job, dict) else str(job)}\n\n"
            f"Include the most relevant portfolio links: {links}\n\n"
            "Output: Subject line and Email body only."
        )
        return self._sanitize_text(self.call_llm(prompt, cache_ttl=DEFAULT_CACHE_TTL, trim_to=800))


# ---------------------------------------------------------------------------
# Placeholder filler (extracted from Chain for clarity)
# ---------------------------------------------------------------------------

class PlaceholderFiller:
    """Replace ``[Tag]`` style placeholders in email text using job/resume data."""

    def __init__(self, job: Dict[str, Any], resume_info: Dict[str, Any]) -> None:
        contact = resume_info.get("contact", {}) if isinstance(resume_info, dict) else {}
        if not isinstance(contact, dict):
            contact = {}
        name = resume_info.get("name") if isinstance(resume_info, dict) else None
        linkedin = contact.get("linkedin") or contact.get("profile")
        email = contact.get("email", "")
        phone = contact.get("phone", "")
        contact_str = ", ".join(filter(None, [email, phone]))

        self._map: Dict[str, str] = {
            "[Your Full Name]": name or "",
            "[Your Name]": name or "",
            "[Candidate Name]": name or "",
            "[Your Contact Information]": contact_str,
            "[Contact Information]": contact_str,
            "[Contact]": contact_str,
            "[Your LinkedIn Profile]": linkedin or "",
            "[Company Name]": job.get("company", "") if isinstance(job, dict) else "",
            "[Job Title]": job.get("role", "") if isinstance(job, dict) else "",
            "[Email]": email,
            "[Your Email]": email,
            "[your email]": email,
            "[Phone]": phone,
            "[Your Phone]": phone,
            "[your phone]": phone,
        }

    def fill(self, text: str) -> str:
        if not isinstance(text, str):
            return text
        for placeholder, value in self._map.items():
            if value:
                text = text.replace(placeholder, value)
        return text