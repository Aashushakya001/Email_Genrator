# import os
# import sys
# import pathlib
# import streamlit as st
# import hashlib
# import threading
# import json
# import time
# from langchain_community.document_loaders import WebBaseLoader

# # Ensure project root is on sys.path so `from app...` imports work when
# # Streamlit executes this file directly (it sets the script directory on
# # sys.path which can make the parent package unavailable).
# _PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
# if str(_PROJECT_ROOT) not in sys.path:
#     sys.path.insert(0, str(_PROJECT_ROOT))

# def _load_local_module(name: str):
#     import importlib.util
#     module_path = _PROJECT_ROOT.joinpath('app', f"{name}.py")
#     spec = importlib.util.spec_from_file_location(f"app.{name}", str(module_path))
#     mod = importlib.util.module_from_spec(spec)
#     spec.loader.exec_module(mod)
#     return mod

# # Try normal package imports first, fall back to loading modules directly from files
# try:
#     from app.chains import Chain
#     from app.utils import clean_text
#     from app.resume_parser import extract_text_from_pdf
#     from app.chat_memory import load_memory, append_message, clear_memory
# except Exception:
#     _chains = _load_local_module('chains')
#     Chain = getattr(_chains, 'Chain')
#     _utils = _load_local_module('utils')
#     clean_text = getattr(_utils, 'clean_text')
#     _rp = _load_local_module('resume_parser')
#     extract_text_from_pdf = getattr(_rp, 'extract_text_from_pdf')
#     _cm = _load_local_module('chat_memory')
#     load_memory = getattr(_cm, 'load_memory')
#     append_message = getattr(_cm, 'append_message')
#     clear_memory = getattr(_cm, 'clear_memory')


# def create_streamlit_app(chain: Chain, clean_text):
#     st.title("📧 Cold Mail Generator — Resume-based")

#     # Allow user to provide Azure OpenAI API key at runtime (overrides env)
#     azure_key = st.sidebar.text_input("Azure OpenAI API Key (optional; overrides env)", type="password")
#     try:
#         # Instantiate Chain without frontend model-selection; Chain will pick available candidate models.
#         # chain = Chain(azure_api_key=azure_key or None)
#         chain=Chain()
#     except Exception as e:
#         st.sidebar.error(str(e))
#         chain = None
#     if chain and getattr(chain, 'deployment', None):
#         st.sidebar.info(f"Model/deployment: {chain.deployment}")
#         if getattr(chain, 'last_error', None):
#             st.sidebar.warning("LLM reported an error during last operation. See UI messages for details.")

#     # Resume upload
#     st.header("Upload Resume")
#     uploaded_file = st.file_uploader("Upload a PDF resume", type=["pdf"])
#     # Keep resume and assistant output across reruns so UI actions (memory show, buttons)
#     # don't cause the generated email to disappear.
#     if 'resume_info' not in st.session_state:
#         st.session_state['resume_info'] = None
#     if 'assistant_output' not in st.session_state:
#         st.session_state['assistant_output'] = None
#     resume_info = st.session_state['resume_info']
#     resumes_dir = os.path.join("app", "resumes")
#     os.makedirs(resumes_dir, exist_ok=True)

#     if uploaded_file is not None:
#         save_path = os.path.join(resumes_dir, uploaded_file.name)
#         with open(save_path, "wb") as f:
#             f.write(uploaded_file.getbuffer())
#         st.success(f"Saved resume to {save_path}")
#         text = extract_text_from_pdf(save_path)
#         try:
#             if chain is None:
#                 st.error("LLM not available. Provide a valid GROQ API key in the sidebar.")
#             else:
#                 # Split pipeline: summarize -> extract skills (heuristic if needed) -> parse
#                 try:
#                     summary = chain.summarize_resume(text)
#                 except Exception:
#                     summary = None

#                 try:
#                     # First attempt LLM parse (structured)
#                     resume_info = chain.parse_resume(text)
#                 except Exception as e:
#                     st.error(f"Failed to parse resume with LLM: {e}")
#                     st.info("Using fallback parser to extract basic resume fields.")
#                     from app.resume_parser import extract_basic_resume_info
#                     resume_info = extract_basic_resume_info(text)

#                 # ensure skills exist: prefer structured skills, else heuristic
#                 if not resume_info.get('skills'):
#                     try:
#                         resume_info['skills'] = chain.extract_skills_no_llm(text)
#                     except Exception:
#                         resume_info['skills'] = resume_info.get('skills') or []

#                 st.subheader("Parsed Resume Info")
#                 st.json(resume_info)
#                 # persist parsed resume so it's available after reruns
#                 st.session_state['resume_info'] = resume_info
#         except Exception as e:
#             st.error(f"Failed to parse resume: {e}")

#     # Chat memory controls
#     st.sidebar.header("Chat Memory")
#     if st.sidebar.button("Show memory"):
#         mem = load_memory()
#         st.sidebar.json(mem)
#     if st.sidebar.button("Clear memory"):
#         clear_memory()
#         st.sidebar.success("Memory cleared")

#     # Quick chat UI (uses memory)
#     st.header("Assistant")
#     user_query = st.text_input("Ask the assistant about the current context")
#     if st.button("Send to assistant") and user_query:
#         append_message("user", user_query)
#         # Use the chain.llm directly to answer using memory (simple concatenation)
#         mem = load_memory()
#         context = "\n".join([m["content"] for m in mem[-10:]])
#         # enforce assistant persona
#         prompt = f"You are Mohan, a business development executive at AtliQ. Use the context and answer concisely.\n\nContext:\n{context}\n\nUser question:\n{user_query}\nAnswer concisely."
#         try:
#             answer = chain.call_llm(prompt, trim_to=1200)
#         except Exception as e:
#             answer = f"LLM error: {e}"
#         append_message("assistant", answer)
#         st.write(answer)

#     st.header("Job URL")
#     url_input = st.text_input("Enter a job posting URL:", value="https://www.linkedin.com/jobs/search-results/?currentJobId=4387321376&keywords=aiml&origin=JOB_SEARCH_PAGE_LOCATION_AUTOCOMPLETE&geoId=115884833")
#     submit_button = st.button("Generate Emails")

#     if submit_button:
#         if chain is None:
#             st.error("LLM not available. Provide a valid GROQ API key in the sidebar.")
#             return
#         if not resume_info:
#             st.error("Please upload and parse a resume first.")
#             return
#         try:
#             # Try a lightweight fetch first
#             loader = WebBaseLoader([url_input])
#             page = loader.load().pop().page_content
#             data = clean_text(page)

#             # detect possible login gate or LinkedIn anti-bot or very short content
#             gated = False
#             if 'signin' in page.lower() or ('linkedin' in url_input.lower() and 'jobs' in url_input.lower() and len(data) < 100):
#                 gated = True
#             if gated:
#                 st.warning("LinkedIn or gated page detected; scraping may be incomplete.")
#                 st.info("Playwright-based fetching is disabled in this environment. Please paste the job description text manually if extraction fails.")

#             # try LLM-based job extraction, fallback to asking user
#             jobs = []
#             poster_info = {}
#             if chain is None:
#                 st.error("LLM not available. Provide a valid Azure OpenAI API key in the sidebar.")
#                 return
#             try:
#                 jobs = chain.extract_jobs(data)
#             except Exception as e:
#                 st.error(f"Failed to extract jobs with LLM: {e}")
#                 st.info("Please paste the job description text into the box below.")
#                 manual = st.text_area("Paste job description (optional)")
#                 if manual:
#                     # try to extract simple fields from pasted job text
#                     import re
#                     role = None
#                     location = None
#                     # look for lines like 'Job Title: ...' or 'Title: ...'
#                     m_role = re.search(r"(?im)^\s*(Job Title|Title)\s*[:\-]\s*(.+)$", manual)
#                     if m_role:
#                         role = m_role.group(2).strip()
#                     # look for 'Location:'
#                     m_loc = re.search(r"(?im)^\s*Location\s*[:\-]\s*(.+)$", manual)
#                     if m_loc:
#                         location = m_loc.group(1).strip()
#                     jobs = [{"role": role, "location": location, "skills": [], "description": manual}]

#             try:
#                 poster_info = chain.extract_job_poster(page)
#             except Exception:
#                 poster_info = {"posted_on": None, "poster_name": None, "poster_link": None, "poster_profile": None, "contact_email": None}

#             st.subheader("Job Poster / Contact info (extracted)")
#             st.json(poster_info)

#             # Internally pick the first job and attach source URL; do NOT display raw job JSON
#             try:
#                 jobs_list = jobs if isinstance(jobs, list) else (jobs or [])
#                 job = jobs_list[0] if jobs_list else {'role': None, 'location': None, 'skills': [], 'description': data}
#                 if isinstance(job, dict):
#                     job['source_url'] = url_input
#             except Exception:
#                 job = {'role': None, 'location': None, 'skills': [], 'description': data, 'source_url': url_input}

#             # Persist job and resume JSON into chat memory so assistant can access them in subsequent messages
#             try:
#                 append_message('system', 'JOB_JSON: ' + json.dumps(job, ensure_ascii=False))
#                 append_message('system', 'RESUME_JSON: ' + json.dumps(resume_info, ensure_ascii=False))
#             except Exception:
#                 pass

#             # Assistant persona: senior HR expert who writes ready-to-send emails
#             persona = (
#                 "You are a senior HR and hiring expert with 50+ years of combined experience in talent acquisition, hiring strategy, and professional communication. "
#                 "You are also an expert in writing concise, high-conversion job application emails. When asked, you must generate a ready-to-send email (Subject line + body). "
#                 "Use the job and resume data present in the conversation memory under keys JOB_JSON and RESUME_JSON. Always include full personal contact details found in the resume (email, phone) and include LinkedIn and GitHub as links when present. "
#                 "If any data is missing, explicitly mention it in a short note but still produce the best possible email."
#             )

#             assistant_prompt = (
#                 persona + "\n\nTask: Produce a ready-to-send application email tailored to the provided job and candidate. Output only the final email text beginning with 'Subject:' followed by a blank line and the email body. Keep body 110-170 words. Include top matching skills and a call-to-action for interview scheduling."
#             )

#             # Include the actual JOB_JSON and RESUME_JSON inline in the prompt so the LLM
#             # receives the precise structured data in the same request (chat memory append
#             # does not automatically feed into a single-prompt LLM call).
#             try:
#                 job_json_str = json.dumps(job, ensure_ascii=False)
#             except Exception:
#                 job_json_str = str(job)
#             try:
#                 resume_json_str = json.dumps(resume_info, ensure_ascii=False)
#             except Exception:
#                 resume_json_str = str(resume_info)

#             full_prompt = assistant_prompt + "\n\nJOB_JSON:\n" + job_json_str + "\n\nRESUME_JSON:\n" + resume_json_str

#             # helper to fill placeholders from resume contact info
#             def _fill_placeholders(text: str, resume: dict) -> str:
#                 if not isinstance(text, str) or not resume:
#                     return text
#                 contact = resume.get('contact') or {}
#                 name = resume.get('name') or ''
#                 email = contact.get('email') or contact.get('Email') or ''
#                 phone = contact.get('phone') or contact.get('Phone') or ''
#                 linkedin = contact.get('linkedin') or contact.get('LinkedIn') or ''
#                 github = contact.get('github') or contact.get('GitHub') or ''
#                 replacements = {
#                     '[Your Full Name]': name,
#                     '[Your Name]': name,
#                     '[your name]': name,
#                     '[Your Contact Information]': ', '.join(filter(None, [email, phone])),
#                     '[your email]': email,
#                     '[your phone]': phone,
#                     '[LinkedIn URL]': linkedin,
#                     '[LinkedIn]': linkedin,
#                     '[GitHub URL]': github,
#                     '[GitHub]': github,
#                 }
#                 # Accept additional common placeholder variants
#                 alt = {
#                     '[Candidate Name]': name,
#                     '[Email]': email,
#                     '[Phone]': phone,
#                     '[Your Email]': email,
#                     '[Your Phone]': phone,
#                     '[Contact]': ', '.join(filter(None, [email, phone])),
#                     '[Contact Information]': ', '.join(filter(None, [email, phone])),
#                 }
#                 replacements.update(alt)
#                 s = text
#                 for k, v in replacements.items():
#                     if v:
#                         s = s.replace(k, v)
#                 return s

#             # Background generation to avoid long blocking calls that can close WebSocket
#             # directory where background results are stored for main thread to pick up
#             BG_RESULTS_DIR = os.path.join('app', 'logs', 'bg_results')
#             os.makedirs(BG_RESULTS_DIR, exist_ok=True)

#             def _background_generate(prompt_text, resume_info_local, job_local, prompt_key):
#                 try:
#                     res = chain.call_llm(prompt_text, trim_to=1600)
#                     filled = _fill_placeholders(res or '', resume_info_local or {})
#                     try:
#                         append_message('assistant', filled)
#                     except Exception:
#                         pass
#                     # write result to a file for the main thread to consume (avoid st.* in background)
#                     out_path = os.path.join(BG_RESULTS_DIR, f"{prompt_key}.json")
#                     with open(out_path, 'w', encoding='utf-8') as fh:
#                         json.dump({'output': filled, 'ts': int(time.time())}, fh, ensure_ascii=False)
#                 except Exception as e:
#                     out_path = os.path.join(BG_RESULTS_DIR, f"{prompt_key}.json")
#                     try:
#                         with open(out_path, 'w', encoding='utf-8') as fh:
#                             json.dump({'error': str(e), 'ts': int(time.time())}, fh, ensure_ascii=False)
#                     except Exception:
#                         pass

#             # Kick off background thread if not already generating
#             # create a prompt key used for matching background result files
#             prompt_key = hashlib.sha256(full_prompt.encode('utf-8')).hexdigest()
#             result_file = os.path.join('app', 'logs', 'bg_results', f"{prompt_key}.json")
#             if not st.session_state.get('generating'):
#                 st.session_state['generating'] = True
#                 st.session_state.pop('assistant_error', None)
#                 thread = threading.Thread(target=_background_generate, args=(full_prompt, resume_info, job, prompt_key), daemon=True)
#                 thread.start()

#             # If background result file exists, load it into session_state and remove file
#             try:
#                 if os.path.exists(result_file):
#                     with open(result_file, 'r', encoding='utf-8') as fh:
#                         j = json.load(fh)
#                     try:
#                         if 'output' in j:
#                             st.session_state['assistant_output'] = j.get('output')
#                         if 'error' in j:
#                             st.session_state['assistant_error'] = j.get('error')
#                     except Exception:
#                         pass
#                     try:
#                         os.remove(result_file)
#                     except Exception:
#                         pass
#                     st.session_state['generating'] = False
#             except Exception:
#                 pass

#             # Show progress and final output
#             st.subheader(f"Email for: {job.get('role', 'Unknown')}")
#             if st.session_state.get('generating'):
#                 st.info('Generating the email — please keep this page open. This may take up to a minute.')
#             if st.session_state.get('assistant_error'):
#                 st.error('Generation error: ' + st.session_state.get('assistant_error'))
#             shown_output = st.session_state.get('assistant_output')
#             if shown_output:
#                 st.code(shown_output, language='markdown')
#             elif not st.session_state.get('generating'):
#                 simple = f"Hello,\n\nI am reaching out regarding the {job.get('role','position')} role. I have experience in {', '.join((resume_info or {}).get('skills') or [])}.\n\nRegards."
#                 st.code(simple, language='markdown')

#             # show poster info if available
#             if poster_info.get('contact_email'):
#                 st.info(f"Contact email found: {poster_info.get('contact_email')}")
#             if poster_info.get('poster_profile'):
#                 st.info(f"Poster profile (LinkedIn): {poster_info.get('poster_profile')}")
#         except Exception as e:
#             st.error(f"An Error Occurred: {e}")


# if __name__ == "__main__":
#     st.set_page_config(layout="wide", page_title="Cold Email Generator", page_icon="📧")
#     create_streamlit_app(None, clean_text)


# """
# main.py — Streamlit front-end for the Cold Email Generator.

# Key fixes vs previous version:
# - Removed broken background-thread pattern (Streamlit reruns kill thread results).
#   Email is now generated synchronously with a spinner — clean and reliable.
# - Chain() is instantiated once, correctly, not re-instantiated inside the render fn.
# - resume_info is always reloaded from session_state before use.
# - poster_info extraction now uses cleaned text (data) not raw HTML (page).
# - Placeholder filling delegated to chains.PlaceholderFiller (no duplication).
# - All st.* calls are in the main thread only.
# """

# from __future__ import annotations

# import json
# import os
# import pathlib
# import sys

# import streamlit as st

# # ---------------------------------------------------------------------------
# # Ensure project root is on sys.path
# # ---------------------------------------------------------------------------
# _PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
# if str(_PROJECT_ROOT) not in sys.path:
#     sys.path.insert(0, str(_PROJECT_ROOT))


# def _load_local_module(name: str):
#     import importlib.util
#     module_path = _PROJECT_ROOT / "app" / f"{name}.py"
#     spec = importlib.util.spec_from_file_location(f"app.{name}", str(module_path))
#     mod = importlib.util.module_from_spec(spec)
#     spec.loader.exec_module(mod)
#     return mod


# try:
#     from app.chains import Chain, PlaceholderFiller
#     from app.utils import clean_text
#     from app.resume_parser import extract_text_from_pdf
#     from app.chat_memory import load_memory, append_message, clear_memory
# except Exception:
#     _chains = _load_local_module("chains")
#     Chain = getattr(_chains, "Chain")
#     PlaceholderFiller = getattr(_chains, "PlaceholderFiller")
#     _utils = _load_local_module("utils")
#     clean_text = getattr(_utils, "clean_text")
#     _rp = _load_local_module("resume_parser")
#     extract_text_from_pdf = getattr(_rp, "extract_text_from_pdf")
#     _cm = _load_local_module("chat_memory")
#     load_memory = getattr(_cm, "load_memory")
#     append_message = getattr(_cm, "append_message")
#     clear_memory = getattr(_cm, "clear_memory")


# # ---------------------------------------------------------------------------
# # Helpers
# # ---------------------------------------------------------------------------

# def _init_chain(api_key: str | None = None) -> Chain | None:
#     """Try to instantiate Chain; return None and show sidebar error on failure."""
#     try:
#         return Chain(azure_api_key=api_key or None)
#     except Exception as exc:
#         st.sidebar.error(f"Chain init failed: {exc}")
#         return None


# def _parse_resume(chain: Chain, pdf_path: str) -> dict:
#     """Extract and parse resume from *pdf_path*; return structured dict."""
#     text = extract_text_from_pdf(pdf_path)

#     try:
#         resume_info = chain.parse_resume(text)
#     except Exception as exc:
#         st.warning(f"LLM resume parse failed ({exc}); using heuristic fallback.")
#         try:
#             from app.resume_parser import extract_basic_resume_info
#             resume_info = extract_basic_resume_info(text)
#         except Exception:
#             resume_info = {}

#     # Ensure skills are populated
#     if not resume_info.get("skills"):
#         resume_info["skills"] = chain.extract_skills_no_llm(text)

#     return resume_info


# def _fetch_page(url: str) -> tuple[str, str, bool]:
#     """Fetch *url* and return (raw_html, cleaned_text, is_gated)."""
#     from langchain_community.document_loaders import WebBaseLoader
#     loader = WebBaseLoader([url])
#     page_html = loader.load().pop().page_content
#     cleaned = clean_text(page_html)

#     gated = "signin" in page_html.lower() or (
#         "linkedin" in url.lower()
#         and "jobs" in url.lower()
#         and len(cleaned) < 100
#     )
#     return page_html, cleaned, gated


# def _extract_job(chain: Chain, cleaned_text: str, url: str) -> dict:
#     """Extract the first job from *cleaned_text*; fall back to a minimal stub."""
#     try:
#         jobs = chain.extract_jobs(cleaned_text)
#         job = (jobs or [{}])[0] if isinstance(jobs, list) else {}
#     except Exception as exc:
#         st.warning(f"Job extraction failed: {exc}")
#         job = {}

#     job.setdefault("role", None)
#     job.setdefault("location", None)
#     job.setdefault("skills", [])
#     job.setdefault("description", cleaned_text)
#     job["source_url"] = url
#     return job


# def _generate_email(chain: Chain, job: dict, resume_info: dict) -> str:
#     """Build the full prompt and call the LLM; return the filled email text."""
#     persona = (
#         "You are a senior HR and hiring expert with 50+ years of combined experience "
#         "in talent acquisition, hiring strategy, and professional communication. "
#         "You are also an expert in writing concise, high-conversion job application emails. "
#         "Generate a ready-to-send email using the job and resume data below. "
#         "Always include the candidate's full contact details (email, phone) and LinkedIn/GitHub "
#         "links when present. If any data is missing, note it briefly but still write the email."
#     )

#     task = (
#         "Output only the final email text starting with 'Subject:' followed by a blank line "
#         "and the email body. Keep the body 110-170 words. Include top 3 matching skills and a "
#         "call-to-action for interview scheduling."
#     )

#     try:
#         job_str = json.dumps(job, ensure_ascii=False)
#     except Exception:
#         job_str = str(job)

#     try:
#         resume_str = json.dumps(resume_info, ensure_ascii=False)
#     except Exception:
#         resume_str = str(resume_info)

#     full_prompt = (
#         f"{persona}\n\n{task}"
#         f"\n\nJOB_JSON:\n{job_str}"
#         f"\n\nRESUME_JSON:\n{resume_str}"
#     )

#     raw = chain.call_llm(full_prompt, trim_to=2000)

#     # Fill any leftover placeholders using resume data
#     filler = PlaceholderFiller(job, resume_info)
#     return filler.fill(raw or "")


# # ---------------------------------------------------------------------------
# # Main Streamlit app
# # ---------------------------------------------------------------------------

# def create_streamlit_app() -> None:
#     st.title("📧 Cold Mail Generator — Resume-based")

#     # ── Sidebar ──────────────────────────────────────────────────────────────
#     st.sidebar.header("Configuration")
#     azure_key = st.sidebar.text_input(
#         "Azure OpenAI API Key (optional; overrides env)", type="password"
#     )

#     # Instantiate chain once per session (cache it so reruns don't recreate it)
#     if "chain" not in st.session_state or (azure_key and azure_key != st.session_state.get("_last_key")):
#         st.session_state["chain"] = _init_chain(azure_key or None)
#         st.session_state["_last_key"] = azure_key

#     chain: Chain | None = st.session_state["chain"]

#     if chain and getattr(chain, "deployment", None):
#         st.sidebar.info(f"Deployment: {chain.deployment}")

#     # ── Chat memory controls ─────────────────────────────────────────────────
#     st.sidebar.header("Chat Memory")
#     if st.sidebar.button("Show memory"):
#         st.sidebar.json(load_memory())
#     if st.sidebar.button("Clear memory"):
#         clear_memory()
#         st.sidebar.success("Memory cleared.")

#     # ── Resume upload ────────────────────────────────────────────────────────
#     st.header("1 · Upload Resume")
#     uploaded_file = st.file_uploader("Upload a PDF resume", type=["pdf"])

#     resumes_dir = os.path.join("app", "resumes")
#     os.makedirs(resumes_dir, exist_ok=True)

#     if uploaded_file is not None and chain is not None:
#         save_path = os.path.join(resumes_dir, uploaded_file.name)
#         with open(save_path, "wb") as fh:
#             fh.write(uploaded_file.getbuffer())
#         st.success(f"Saved to {save_path}")

#         with st.spinner("Parsing resume…"):
#             resume_info = _parse_resume(chain, save_path)

#         st.subheader("Parsed Resume")
#         st.json(resume_info)
#         st.session_state["resume_info"] = resume_info

#     # ── Quick assistant chat ─────────────────────────────────────────────────
#     st.header("2 · Assistant")
#     user_query = st.text_input("Ask the assistant a question")
#     if st.button("Send") and user_query and chain:
#         append_message("user", user_query)
#         mem = load_memory()
#         context = "\n".join(m["content"] for m in mem[-10:])
#         prompt = (
#             "You are Mohan, a business development executive at AtliQ. "
#             "Answer concisely using the context below.\n\n"
#             f"Context:\n{context}\n\nQuestion:\n{user_query}"
#         )
#         try:
#             answer = chain.call_llm(prompt, trim_to=1200)
#         except Exception as exc:
#             answer = f"LLM error: {exc}"
#         append_message("assistant", answer)
#         st.write(answer)

#     # ── Job URL + email generation ───────────────────────────────────────────
#     st.header("3 · Job URL")
#     url_input = st.text_input(
#         "Enter a job posting URL:",
#         value="https://www.linkedin.com/jobs/search-results/?currentJobId=4387321376",
#     )
#     generate_btn = st.button("Generate Email")

#     if generate_btn:
#         # Guard: chain must be available
#         if chain is None:
#             st.error("LLM not available. Provide a valid Azure OpenAI API key in the sidebar.")
#             return

#         # Guard: resume must be parsed
#         resume_info: dict = st.session_state.get("resume_info") or {}
#         if not resume_info:
#             st.error("Please upload and parse a resume first (Step 1).")
#             return

#         # ── Fetch page ───────────────────────────────────────────────────────
#         try:
#             with st.spinner("Fetching job page…"):
#                 page_html, cleaned_text, gated = _fetch_page(url_input)
#         except Exception as exc:
#             st.error(f"Failed to fetch URL: {exc}")
#             return

#         if gated:
#             st.warning("LinkedIn or gated page detected; scraping may be incomplete.")
#             st.info(
#                 "Playwright-based fetching is disabled in this environment. "
#                 "Please paste the job description text manually if extraction fails."
#             )

#         # ── Extract job ──────────────────────────────────────────────────────
#         with st.spinner("Extracting job details…"):
#             job = _extract_job(chain, cleaned_text, url_input)

#         # ── Extract poster info (use cleaned text, not raw HTML) ─────────────
#         with st.spinner("Extracting poster/contact info…"):
#             try:
#                 # BUG FIX: was passing raw page_html; now passes cleaned_text
#                 poster_info = chain.extract_job_poster(cleaned_text)
#             except Exception:
#                 poster_info = {}

#         st.subheader("Job Poster / Contact info (extracted)")
#         st.json(poster_info)

#         # ── Persist to chat memory ───────────────────────────────────────────
#         try:
#             append_message("system", "JOB_JSON: " + json.dumps(job, ensure_ascii=False))
#             append_message("system", "RESUME_JSON: " + json.dumps(resume_info, ensure_ascii=False))
#         except Exception:
#             pass

#         # ── Generate email (synchronous — no background thread) ──────────────
#         st.subheader(f"Email for: {job.get('role') or 'Unknown Role'}")

#         with st.spinner("Generating email… (this may take ~30 s)"):
#             try:
#                 email_text = _generate_email(chain, job, resume_info)
#             except Exception as exc:
#                 st.error(f"Email generation failed: {exc}")
#                 # Produce a sensible fallback so the user still gets something
#                 skills_str = ", ".join(resume_info.get("skills") or [])
#                 email_text = (
#                     f"Subject: Application for {job.get('role', 'the position')}\n\n"
#                     f"Dear Hiring Team,\n\n"
#                     f"I am writing to express my interest in the {job.get('role', 'position')} role. "
#                     f"I bring experience in {skills_str}.\n\n"
#                     f"I would welcome the opportunity to discuss how my background aligns with your needs.\n\n"
#                     f"Best regards,\n{resume_info.get('name', '[Your Name]')}"
#                 )

#         st.session_state["assistant_output"] = email_text
#         append_message("assistant", email_text)

#         st.code(email_text, language="markdown")

#         # ── Contact info callouts ────────────────────────────────────────────
#         if poster_info.get("contact_email"):
#             st.info(f"Contact email found: {poster_info['contact_email']}")
#         if poster_info.get("poster_profile"):
#             st.info(f"Poster LinkedIn: {poster_info['poster_profile']}")


# # ---------------------------------------------------------------------------
# # Entry point
# # ---------------------------------------------------------------------------

# if __name__ == "__main__":
#     st.set_page_config(layout="wide", page_title="Cold Email Generator", page_icon="📧")
#     create_streamlit_app()




# ############################################
"""
main.py — Streamlit front-end for the Cold Email Generator.

Key fixes in this version:
1. Resume validation guard — blocks email generation if resume has no real contact data,
   preventing the LLM from hallucinating "John Doe / john.doe@example.com" etc.
2. LLM prompt is now hallucination-proof — explicitly instructs the model to use ONLY
   values present in RESUME_JSON and to omit (not invent) anything missing.
3. Company name extracted from raw HTML og:site_name / <title> before clean_text runs.
4. clean_text no longer strips URLs/emails (fixed in utils.py).
5. Removed useless standalone "Assistant" chat block.
6. Email Refinement Chat (Step 3) with full persistent memory.
7. Chain cached in session_state — not re-created on every Streamlit rerun.
8. pdfplumber used first for better PDF text extraction (falls back to PyPDF2).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from typing import Any

import streamlit as st

# ── sys.path fix ──────────────────────────────────────────────────────────────
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _load_local_module(name: str):
    import importlib.util
    path = _PROJECT_ROOT / "app" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"app.{name}", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    from app.chains import Chain, PlaceholderFiller
    from app.utils import clean_text
    from app.resume_parser import extract_text_from_pdf, extract_basic_resume_info
    from app.chat_memory import (
        load_memory, append_message, clear_memory,
        load_email_thread, start_email_thread,
        append_email_thread, clear_email_thread,
    )
except Exception:
    _chains = _load_local_module("chains")
    Chain = getattr(_chains, "Chain")
    PlaceholderFiller = getattr(_chains, "PlaceholderFiller")
    _utils = _load_local_module("utils")
    clean_text = getattr(_utils, "clean_text")
    _rp = _load_local_module("resume_parser")
    extract_text_from_pdf = getattr(_rp, "extract_text_from_pdf")
    extract_basic_resume_info = getattr(_rp, "extract_basic_resume_info")
    _cm = _load_local_module("chat_memory")
    load_memory = getattr(_cm, "load_memory")
    append_message = getattr(_cm, "append_message")
    clear_memory = getattr(_cm, "clear_memory")
    load_email_thread = getattr(_cm, "load_email_thread")
    start_email_thread = getattr(_cm, "start_email_thread")
    append_email_thread = getattr(_cm, "append_email_thread")
    clear_email_thread = getattr(_cm, "clear_email_thread")


# ── Constants ─────────────────────────────────────────────────────────────────

# Placeholder patterns the LLM might still emit even after instruction
_HALLUCINATION_PATTERNS = re.compile(
    r"\bjohn\s+doe\b|john\.doe@|example\.com|johndoe|"
    r"98765\s*43210|linkedin\.com/in/johndoe|github\.com/johndoe|"
    r"\[LinkedIn\s+Profile[^\]]*\]|\[GitHub\s+Link[^\]]*\]|"
    r"\[Your\s+\w+[^\]]*\]|\[Company\s+Name\]",
    re.I,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _init_chain(api_key: str | None = None) -> Chain | None:
    try:
        return Chain(azure_api_key=api_key or None)
    except Exception as exc:
        st.sidebar.error(f"Chain init failed: {exc}")
        return None


def _resume_is_valid(resume_info: dict) -> tuple[bool, str]:
    """Return (is_valid, reason). Blocks generation if resume has no real data."""
    if not resume_info:
        return False, "No resume data found. Please upload your PDF resume first."

    contact = resume_info.get("contact") or {}
    name = resume_info.get("name") or ""

    if not name or len(name.strip()) < 2:
        return False, "Could not extract your name from the resume. Check if the PDF is text-based (not a scanned image)."

    if not contact.get("email"):
        return False, "Could not extract an email address from your resume. Ensure your resume contains a valid email."

    # Sanity check: name should not look like a hallucinated placeholder
    if re.search(r"\bjohn\s*doe\b|candidate\s*name|your\s*name", name, re.I):
        return False, "Extracted name looks like a placeholder. Please re-upload your resume."

    return True, ""


def _parse_resume(chain: Chain, pdf_path: str) -> dict:
    """Extract text from PDF and parse into structured resume dict."""
    text = extract_text_from_pdf(pdf_path)

    if not text or len(text.strip()) < 50:
        st.error(
            "Could not extract text from the PDF. "
            "Make sure it is a text-based PDF (not a scanned image). "
            "Try copy-pasting text from the PDF manually."
        )
        return {}

    # Try LLM parse first
    try:
        info = chain.parse_resume(text)
    except Exception as exc:
        st.warning(f"LLM resume parse failed ({exc}); using heuristic parser.")
        info = {}

    # If LLM returned empty or no contact, fall back to heuristic
    if not info or not (info.get("contact") or {}).get("email"):
        st.info("Using heuristic parser to extract resume fields.")
        heuristic = extract_basic_resume_info(text)
        # Merge: prefer LLM values but fill missing ones from heuristic
        if not info:
            info = heuristic
        else:
            for key in ("name", "contact", "skills", "education", "experience_summary"):
                if not info.get(key) and heuristic.get(key):
                    info[key] = heuristic[key]

    # Ensure skills are populated
    if not info.get("skills"):
        try:
            info["skills"] = chain.extract_skills_no_llm(text)
        except Exception:
            info["skills"] = []

    return info


def _extract_company_from_html(html: str) -> str | None:
    """Extract company name from raw HTML before clean_text removes structure."""
    for pattern in [
        r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']{2,80})["\']',
        r'<meta[^>]+content=["\']([^"\']{2,80})["\'][^>]+property=["\']og:site_name["\']',
        r'<meta[^>]+name=["\']author["\'][^>]+content=["\']([^"\']{2,80})["\']',
    ]:
        m = re.search(pattern, html, re.I)
        if m:
            val = m.group(1).strip()
            # Reject generic values
            if val.lower() not in ("jobs", "careers", "linkedin", "indeed", "glassdoor"):
                return val

    # Fallback: "Role at Company" or "Role | Company" in <title>
    m = re.search(r"<title[^>]*>([^<]{5,200})</title>", html, re.I)
    if m:
        title = m.group(1)
        for sep in (" at ", " | ", " - ", " — ", " – "):
            if sep in title:
                parts = title.split(sep, 1)
                if len(parts) == 2:
                    company = parts[1].strip().split(" — ")[0].split(" | ")[0].strip()
                    if 2 < len(company) < 80:
                        return company
    return None


def _fetch_page(url: str) -> tuple[str, str, bool]:
    """Fetch URL, return (raw_html, cleaned_text, is_gated)."""
    from langchain_community.document_loaders import WebBaseLoader
    loader = WebBaseLoader([url])
    html = loader.load().pop().page_content
    cleaned = clean_text(html)
    gated = (
        "signin" in html.lower()
        or "log in" in html.lower()
        or (
            "linkedin" in url.lower()
            and "jobs" in url.lower()
            and len(cleaned) < 300
        )
    )
    return html, cleaned, gated


def _extract_job(chain: Chain, cleaned: str, url: str, company: str | None) -> dict:
    """Extract job dict from cleaned page text."""
    try:
        jobs = chain.extract_jobs(cleaned)
        job = (jobs or [{}])[0] if isinstance(jobs, list) else {}
    except Exception as exc:
        st.warning(f"Job extraction failed: {exc}")
        job = {}

    job.setdefault("role", None)
    job.setdefault("location", None)
    job.setdefault("skills", [])
    job.setdefault("description", cleaned[:3000])  # cap description size

    # Inject company extracted from raw HTML
    if company and not job.get("company"):
        job["company"] = company

    job["source_url"] = url
    return job


def _build_email_prompt(job: dict, resume_info: dict) -> str:
    """Build a hallucination-proof email generation prompt."""
    contact = resume_info.get("contact") or {}

    # Pre-format contact block so LLM doesn't need to guess structure
    contact_lines = []
    if resume_info.get("name"):
        contact_lines.append(f"Name: {resume_info['name']}")
    if contact.get("email"):
        contact_lines.append(f"Email: {contact['email']}")
    if contact.get("phone"):
        contact_lines.append(f"Phone: {contact['phone']}")
    if contact.get("linkedin"):
        contact_lines.append(f"LinkedIn: {contact['linkedin']}")
    if contact.get("github"):
        contact_lines.append(f"GitHub: {contact['github']}")

    contact_block = "\n".join(contact_lines) if contact_lines else "NOT PROVIDED"

    try:
        job_str = json.dumps(job, ensure_ascii=False)
        resume_str = json.dumps(resume_info, ensure_ascii=False)
    except Exception:
        job_str, resume_str = str(job), str(resume_info)

    return f"""You are an expert job application email writer.

STRICT RULES — violating any rule makes the email unusable:
1. Use ONLY the contact details listed in CANDIDATE CONTACT below. NEVER invent or guess any value.
2. Use ONLY the company name from JOB_JSON. NEVER invent a company name. If company is null, write "your company".
3. If LinkedIn or GitHub is NOT listed in CANDIDATE CONTACT, do NOT include that line at all.
4. Do NOT write placeholder text like [LinkedIn Profile] or [Your Name] — if a value is missing, omit the line.
5. Sign the email with the candidate's REAL name and contact details from CANDIDATE CONTACT only.

CANDIDATE CONTACT (use EXACTLY these values, nothing else):
{contact_block}

JOB_JSON:
{job_str}

RESUME_JSON (for skills and experience context only):
{resume_str}

TASK:
Write a ready-to-send job application email.
- Start with: Subject: <subject line>
- Then a blank line
- Then the email body (110-170 words)
- Mention top 3 matching skills
- End with a call-to-action for interview scheduling
- Sign off with the candidate's real name and the contact details from CANDIDATE CONTACT

Output ONLY the email text. No explanations, no JSON, no preamble."""


def _strip_hallucinations(text: str, resume_info: dict) -> tuple[str, list[str]]:
    """Remove any hallucinated values from generated email and return (clean_text, warnings)."""
    warnings = []
    contact = resume_info.get("contact") or {}
    real_email = contact.get("email", "")
    real_name = resume_info.get("name", "")

    # Detect hallucinated email (different from real one)
    found_emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    for fe in found_emails:
        if real_email and fe.lower() != real_email.lower() and "example.com" in fe.lower():
            text = text.replace(fe, real_email)
            warnings.append(f"Replaced hallucinated email '{fe}' with '{real_email}'")

    # Detect known hallucination patterns
    if _HALLUCINATION_PATTERNS.search(text):
        warnings.append(
            "⚠️ The email may contain placeholder or hallucinated values. "
            "Please review carefully before sending."
        )

    return text, warnings


def _generate_email(chain: Chain, job: dict, resume_info: dict) -> tuple[str, list[str]]:
    """Generate email and return (email_text, warnings)."""
    prompt = _build_email_prompt(job, resume_info)
    raw = chain.call_llm(prompt, trim_to=2800)

    # Fill any remaining bracket-style placeholders
    filled = PlaceholderFiller(job, resume_info).fill(raw or "")

    # Post-process: strip hallucinations
    clean, warnings = _strip_hallucinations(filled, resume_info)
    return clean, warnings


def _refine_email(chain: Chain, user_instruction: str) -> str:
    """Refine the email using the full thread as context."""
    append_email_thread("user", user_instruction)
    thread = load_email_thread()

    # Flatten thread into a single prompt string
    parts = []
    for msg in thread[:-1]:  # exclude last user msg (already in instruction)
        label = {"system": "SYSTEM", "assistant": "ASSISTANT", "user": "USER"}.get(
            msg["role"], msg["role"].upper()
        )
        parts.append(f"[{label}]\n{msg['content']}")

    prompt = (
        "\n\n".join(parts)
        + f"\n\n[USER]\n{user_instruction}"
        + "\n\n[ASSISTANT]\n"
        "Rewrite the COMPLETE updated email (Subject + body) applying the instruction above. "
        "Keep all real contact details. Do not invent any values."
    )

    raw = chain.call_llm(prompt, trim_to=3000)
    job = st.session_state.get("current_job", {})
    resume_info = st.session_state.get("resume_info", {})
    result = PlaceholderFiller(job, resume_info).fill(raw or "")
    result, _ = _strip_hallucinations(result, resume_info)
    append_email_thread("assistant", result)
    return result


# ── Streamlit app ──────────────────────────────────────────────────────────────

def create_streamlit_app() -> None:
    st.title("📧 Cold Email Generator — Resume-based")

    # ── Sidebar ───────────────────────────────────────────────────────────────
    st.sidebar.header("⚙️ Configuration")
    azure_key = st.sidebar.text_input(
        "Azure OpenAI API Key (optional; overrides .env)", type="password"
    )

    # Cache chain once per session
    if "chain" not in st.session_state or (
        azure_key and azure_key != st.session_state.get("_last_key")
    ):
        st.session_state["chain"] = _init_chain(azure_key or None)
        st.session_state["_last_key"] = azure_key

    chain: Chain | None = st.session_state["chain"]

    if chain and getattr(chain, "deployment", None):
        st.sidebar.info(f"Model: {chain.deployment}")

    st.sidebar.divider()
    st.sidebar.header("🗑️ Memory")
    if st.sidebar.button("Clear all memory"):
        clear_memory()
        clear_email_thread()
        st.session_state.pop("assistant_output", None)
        st.session_state.pop("current_job", None)
        st.session_state.pop("resume_info", None)
        st.sidebar.success("All memory cleared.")

    # ── Step 1: Resume ────────────────────────────────────────────────────────
    st.header("1 · Upload Resume")

    uploaded_file = st.file_uploader("Upload your PDF resume", type=["pdf"])

    resumes_dir = os.path.join("app", "resumes")
    os.makedirs(resumes_dir, exist_ok=True)

    if uploaded_file is not None:
        if chain is None:
            st.error("LLM not available. Add your Azure API key in the sidebar.")
        else:
            save_path = os.path.join(resumes_dir, uploaded_file.name)
            with open(save_path, "wb") as fh:
                fh.write(uploaded_file.getbuffer())

            with st.spinner("Parsing resume…"):
                resume_info = _parse_resume(chain, save_path)

            if resume_info:
                # Validate before storing
                valid, reason = _resume_is_valid(resume_info)
                if not valid:
                    st.error(f"Resume validation failed: {reason}")
                    st.info(
                        "Tips:\n"
                        "- Make sure your PDF is not a scanned image\n"
                        "- Ensure your name and email are clearly visible\n"
                        "- Try copy-pasting your resume text into a .txt and re-uploading"
                    )
                else:
                    st.success("✅ Resume parsed successfully")
                    with st.expander("View parsed resume data", expanded=False):
                        st.json(resume_info)

                    # Show what was extracted
                    contact = resume_info.get("contact", {})
                    cols = st.columns(4)
                    cols[0].metric("Name", resume_info.get("name") or "—")
                    cols[1].metric("Email", contact.get("email") or "❌ Not found")
                    cols[2].metric("LinkedIn", "✅ Found" if contact.get("linkedin") else "❌ Not found")
                    cols[3].metric("GitHub", "✅ Found" if contact.get("github") else "❌ Not found")

                    st.session_state["resume_info"] = resume_info

    # Show currently loaded resume if present from a previous upload
    elif st.session_state.get("resume_info"):
        st.info("✅ Resume already loaded from this session.")
        with st.expander("View current resume data", expanded=False):
            st.json(st.session_state["resume_info"])

    # ── Step 2: Job URL ───────────────────────────────────────────────────────
    st.header("2 · Job URL")
    url_input = st.text_input(
        "Enter a job posting URL:",
        value="https://www.jforcesolutions.com/jobs/machine-learning-engineer",
    )

    # Manual paste fallback (for gated/LinkedIn pages)
    with st.expander("📋 Or paste job description manually (for LinkedIn / gated pages)"):
        manual_jd = st.text_area(
            "Paste the full job description text here:",
            height=200,
            placeholder="Paste job description text if the URL is gated or LinkedIn-based…",
        )

    generate_btn = st.button("🚀 Generate Email", type="primary")

    if generate_btn:
        if chain is None:
            st.error("LLM not available. Add your Azure API key in the sidebar.")
            return

        resume_info: dict = st.session_state.get("resume_info") or {}

        # GUARD: block generation if resume is missing or invalid
        valid, reason = _resume_is_valid(resume_info)
        if not valid:
            st.error(f"Cannot generate email: {reason}")
            return

        # Use manual paste if provided (bypasses web fetch)
        if manual_jd and manual_jd.strip():
            st.info("Using manually pasted job description.")
            page_html = ""
            cleaned_text = manual_jd.strip()
            gated = False
            company = None
        else:
            try:
                with st.spinner("Fetching job page…"):
                    page_html, cleaned_text, gated = _fetch_page(url_input)
            except Exception as exc:
                st.error(f"Failed to fetch URL: {exc}")
                st.info("You can paste the job description manually using the expander above.")
                return

            if gated:
                st.warning(
                    "⚠️ LinkedIn or gated page detected — full job text may be unavailable. "
                    "For best results, paste the job description manually above."
                )

            company = _extract_company_from_html(page_html)

        # Extract company from HTML if not from manual paste
        if not manual_jd:
            company = _extract_company_from_html(page_html)
        else:
            company = None  # User can add in refinement chat

        # Extract poster/contact info
        with st.spinner("Extracting contact info…"):
            try:
                poster_info = chain.extract_job_poster(cleaned_text)
            except Exception:
                poster_info = {}

        with st.expander("📋 Job Poster / Contact info", expanded=True):
            st.json(poster_info)

        # Extract job details
        with st.spinner("Extracting job details…"):
            job = _extract_job(chain, cleaned_text, url_input, company)

        # Store to global memory
        try:
            append_message("system", "JOB_JSON: " + json.dumps(job, ensure_ascii=False))
            append_message("system", "RESUME_JSON: " + json.dumps(resume_info, ensure_ascii=False))
        except Exception:
            pass

        # Generate email
        st.subheader(f"📨 Email for: {job.get('role') or 'Unknown Role'}")

        with st.spinner("Generating email… (may take ~30 s)"):
            try:
                email_text, warnings = _generate_email(chain, job, resume_info)
            except Exception as exc:
                st.error(f"Email generation failed: {exc}")
                # Minimal safe fallback using only verified resume data
                contact = resume_info.get("contact", {})
                name = resume_info.get("name", "")
                skills_str = ", ".join(resume_info.get("skills") or [])
                lines = [
                    f"Subject: Application for {job.get('role', 'the position')}",
                    "",
                    f"Dear Hiring Team,",
                    "",
                    f"I am writing to express my interest in the {job.get('role', 'position')} "
                    f"role at {job.get('company', 'your company')}. "
                    f"I bring hands-on experience in {skills_str}.",
                    "",
                    "I would welcome the opportunity to discuss how my background aligns with your needs.",
                    "",
                    "Best regards,",
                    name,
                ]
                if contact.get("email"):
                    lines.append(contact["email"])
                if contact.get("phone"):
                    lines.append(contact["phone"])
                if contact.get("linkedin"):
                    lines.append(f"LinkedIn: {contact['linkedin']}")
                if contact.get("github"):
                    lines.append(f"GitHub: {contact['github']}")
                email_text = "\n".join(lines)
                warnings = []

        # Show warnings
        for w in warnings:
            st.warning(w)

        # Store for refinement
        st.session_state["assistant_output"] = email_text
        st.session_state["current_job"] = job
        append_message("assistant", email_text)
        start_email_thread(job, resume_info, email_text)

        st.code(email_text, language="markdown")

        if poster_info.get("contact_email"):
            st.info(f"📬 Send to: {poster_info['contact_email']}")
        if poster_info.get("poster_profile"):
            st.info(f"🔗 Poster LinkedIn: {poster_info['poster_profile']}")

    # ── Step 3: Email Refinement Chat ─────────────────────────────────────────
    if st.session_state.get("assistant_output"):
        st.divider()
        st.header("3 · Refine Your Email")
        st.caption(
            "Give instructions to improve the email. "
            "The AI remembers the full conversation and rewrites the complete email each time. "
            "Your real contact details are always preserved."
        )

        # Render conversation history
        thread = load_email_thread()
        for msg in thread[1:]:  # skip system message
            if msg["role"] == "assistant":
                with st.chat_message("assistant", avatar="🤖"):
                    st.code(msg["content"], language="markdown")
            elif msg["role"] == "user":
                with st.chat_message("user", avatar="🧑"):
                    st.write(msg["content"])

        # Chat input
        user_instruction = st.chat_input(
            "e.g. 'Make it more formal', 'Add my GitHub link', "
            "'Shorten to 100 words', 'Mention my RAG project'…"
        )

        if user_instruction:
            chain_now: Chain | None = st.session_state.get("chain")
            if chain_now is None:
                st.error("LLM not available.")
            else:
                with st.chat_message("user", avatar="🧑"):
                    st.write(user_instruction)
                with st.chat_message("assistant", avatar="🤖"):
                    with st.spinner("Rewriting email…"):
                        refined = _refine_email(chain_now, user_instruction)
                    st.code(refined, language="markdown")
                st.session_state["assistant_output"] = refined


if __name__ == "__main__":
    st.set_page_config(layout="wide", page_title="Cold Email Generator", page_icon="📧")
    create_streamlit_app()