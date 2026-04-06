import os
import sys
import pathlib
import streamlit as st
import hashlib
import threading
import json
import time
from langchain_community.document_loaders import WebBaseLoader

# Ensure project root is on sys.path so `from app...` imports work when
# Streamlit executes this file directly (it sets the script directory on
# sys.path which can make the parent package unavailable).
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

def _load_local_module(name: str):
    import importlib.util
    module_path = _PROJECT_ROOT.joinpath('app', f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"app.{name}", str(module_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# Try normal package imports first, fall back to loading modules directly from files
try:
    from app.chains import Chain
    from app.utils import clean_text
    from app.resume_parser import extract_text_from_pdf
    from app.chat_memory import load_memory, append_message, clear_memory
except Exception:
    _chains = _load_local_module('chains')
    Chain = getattr(_chains, 'Chain')
    _utils = _load_local_module('utils')
    clean_text = getattr(_utils, 'clean_text')
    _rp = _load_local_module('resume_parser')
    extract_text_from_pdf = getattr(_rp, 'extract_text_from_pdf')
    _cm = _load_local_module('chat_memory')
    load_memory = getattr(_cm, 'load_memory')
    append_message = getattr(_cm, 'append_message')
    clear_memory = getattr(_cm, 'clear_memory')


def create_streamlit_app(chain: Chain, clean_text):
    st.title("📧 Cold Mail Generator — Resume-based")

    # Allow user to provide Azure OpenAI API key at runtime (overrides env)
    azure_key = st.sidebar.text_input("Azure OpenAI API Key (optional; overrides env)", type="password")
    try:
        # Instantiate Chain without frontend model-selection; Chain will pick available candidate models.
        chain = Chain(azure_api_key=azure_key or None)
    except Exception as e:
        st.sidebar.error(str(e))
        chain = None
    if chain and getattr(chain, 'deployment', None):
        st.sidebar.info(f"Model/deployment: {chain.deployment}")
        if getattr(chain, 'last_error', None):
            st.sidebar.warning("LLM reported an error during last operation. See UI messages for details.")

    # Resume upload
    st.header("Upload Resume")
    uploaded_file = st.file_uploader("Upload a PDF resume", type=["pdf"])
    # Keep resume and assistant output across reruns so UI actions (memory show, buttons)
    # don't cause the generated email to disappear.
    if 'resume_info' not in st.session_state:
        st.session_state['resume_info'] = None
    if 'assistant_output' not in st.session_state:
        st.session_state['assistant_output'] = None
    resume_info = st.session_state['resume_info']
    resumes_dir = os.path.join("app", "resumes")
    os.makedirs(resumes_dir, exist_ok=True)

    if uploaded_file is not None:
        save_path = os.path.join(resumes_dir, uploaded_file.name)
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.success(f"Saved resume to {save_path}")
        text = extract_text_from_pdf(save_path)
        try:
            if chain is None:
                st.error("LLM not available. Provide a valid GROQ API key in the sidebar.")
            else:
                # Split pipeline: summarize -> extract skills (heuristic if needed) -> parse
                try:
                    summary = chain.summarize_resume(text)
                except Exception:
                    summary = None

                try:
                    # First attempt LLM parse (structured)
                    resume_info = chain.parse_resume(text)
                except Exception as e:
                    st.error(f"Failed to parse resume with LLM: {e}")
                    st.info("Using fallback parser to extract basic resume fields.")
                    from app.resume_parser import extract_basic_resume_info
                    resume_info = extract_basic_resume_info(text)

                # ensure skills exist: prefer structured skills, else heuristic
                if not resume_info.get('skills'):
                    try:
                        resume_info['skills'] = chain.extract_skills_no_llm(text)
                    except Exception:
                        resume_info['skills'] = resume_info.get('skills') or []

                st.subheader("Parsed Resume Info")
                st.json(resume_info)
                # persist parsed resume so it's available after reruns
                st.session_state['resume_info'] = resume_info
        except Exception as e:
            st.error(f"Failed to parse resume: {e}")

    # Chat memory controls
    st.sidebar.header("Chat Memory")
    if st.sidebar.button("Show memory"):
        mem = load_memory()
        st.sidebar.json(mem)
    if st.sidebar.button("Clear memory"):
        clear_memory()
        st.sidebar.success("Memory cleared")

    # Quick chat UI (uses memory)
    st.header("Assistant")
    user_query = st.text_input("Ask the assistant about the current context")
    if st.button("Send to assistant") and user_query:
        append_message("user", user_query)
        # Use the chain.llm directly to answer using memory (simple concatenation)
        mem = load_memory()
        context = "\n".join([m["content"] for m in mem[-10:]])
        # enforce assistant persona
        prompt = f"You are Mohan, a business development executive at AtliQ. Use the context and answer concisely.\n\nContext:\n{context}\n\nUser question:\n{user_query}\nAnswer concisely."
        try:
            answer = chain.call_llm(prompt, trim_to=1200)
        except Exception as e:
            answer = f"LLM error: {e}"
        append_message("assistant", answer)
        st.write(answer)

    st.header("Job URL")
    url_input = st.text_input("Enter a job posting URL:", value="https://www.linkedin.com/jobs/search-results/?currentJobId=4387321376&keywords=aiml&origin=JOB_SEARCH_PAGE_LOCATION_AUTOCOMPLETE&geoId=115884833")
    submit_button = st.button("Generate Emails")

    if submit_button:
        if chain is None:
            st.error("LLM not available. Provide a valid GROQ API key in the sidebar.")
            return
        if not resume_info:
            st.error("Please upload and parse a resume first.")
            return
        try:
            # Try a lightweight fetch first
            loader = WebBaseLoader([url_input])
            page = loader.load().pop().page_content
            data = clean_text(page)

            # detect possible login gate or LinkedIn anti-bot or very short content
            gated = False
            if 'signin' in page.lower() or ('linkedin' in url_input.lower() and 'jobs' in url_input.lower() and len(data) < 100):
                gated = True
            if gated:
                st.warning("LinkedIn or gated page detected; scraping may be incomplete.")
                st.info("Playwright-based fetching is disabled in this environment. Please paste the job description text manually if extraction fails.")

            # try LLM-based job extraction, fallback to asking user
            jobs = []
            poster_info = {}
            if chain is None:
                st.error("LLM not available. Provide a valid Azure OpenAI API key in the sidebar.")
                return
            try:
                jobs = chain.extract_jobs(data)
            except Exception as e:
                st.error(f"Failed to extract jobs with LLM: {e}")
                st.info("Please paste the job description text into the box below.")
                manual = st.text_area("Paste job description (optional)")
                if manual:
                    # try to extract simple fields from pasted job text
                    import re
                    role = None
                    location = None
                    # look for lines like 'Job Title: ...' or 'Title: ...'
                    m_role = re.search(r"(?im)^\s*(Job Title|Title)\s*[:\-]\s*(.+)$", manual)
                    if m_role:
                        role = m_role.group(2).strip()
                    # look for 'Location:'
                    m_loc = re.search(r"(?im)^\s*Location\s*[:\-]\s*(.+)$", manual)
                    if m_loc:
                        location = m_loc.group(1).strip()
                    jobs = [{"role": role, "location": location, "skills": [], "description": manual}]

            try:
                poster_info = chain.extract_job_poster(page)
            except Exception:
                poster_info = {"posted_on": None, "poster_name": None, "poster_link": None, "poster_profile": None, "contact_email": None}

            st.subheader("Job Poster / Contact info (extracted)")
            st.json(poster_info)

            # Internally pick the first job and attach source URL; do NOT display raw job JSON
            try:
                jobs_list = jobs if isinstance(jobs, list) else (jobs or [])
                job = jobs_list[0] if jobs_list else {'role': None, 'location': None, 'skills': [], 'description': data}
                if isinstance(job, dict):
                    job['source_url'] = url_input
            except Exception:
                job = {'role': None, 'location': None, 'skills': [], 'description': data, 'source_url': url_input}

            # Persist job and resume JSON into chat memory so assistant can access them in subsequent messages
            try:
                append_message('system', 'JOB_JSON: ' + json.dumps(job, ensure_ascii=False))
                append_message('system', 'RESUME_JSON: ' + json.dumps(resume_info, ensure_ascii=False))
            except Exception:
                pass

            # Assistant persona: senior HR expert who writes ready-to-send emails
            persona = (
                "You are a senior HR and hiring expert with 50+ years of combined experience in talent acquisition, hiring strategy, and professional communication. "
                "You are also an expert in writing concise, high-conversion job application emails. When asked, you must generate a ready-to-send email (Subject line + body). "
                "Use the job and resume data present in the conversation memory under keys JOB_JSON and RESUME_JSON. Always include full personal contact details found in the resume (email, phone) and include LinkedIn and GitHub as links when present. "
                "If any data is missing, explicitly mention it in a short note but still produce the best possible email."
            )

            assistant_prompt = (
                persona + "\n\nTask: Produce a ready-to-send application email tailored to the provided job and candidate. Output only the final email text beginning with 'Subject:' followed by a blank line and the email body. Keep body 110-170 words. Include top matching skills and a call-to-action for interview scheduling."
            )

            # Include the actual JOB_JSON and RESUME_JSON inline in the prompt so the LLM
            # receives the precise structured data in the same request (chat memory append
            # does not automatically feed into a single-prompt LLM call).
            try:
                job_json_str = json.dumps(job, ensure_ascii=False)
            except Exception:
                job_json_str = str(job)
            try:
                resume_json_str = json.dumps(resume_info, ensure_ascii=False)
            except Exception:
                resume_json_str = str(resume_info)

            full_prompt = assistant_prompt + "\n\nJOB_JSON:\n" + job_json_str + "\n\nRESUME_JSON:\n" + resume_json_str

            # helper to fill placeholders from resume contact info
            def _fill_placeholders(text: str, resume: dict) -> str:
                if not isinstance(text, str) or not resume:
                    return text
                contact = resume.get('contact') or {}
                name = resume.get('name') or ''
                email = contact.get('email') or contact.get('Email') or ''
                phone = contact.get('phone') or contact.get('Phone') or ''
                linkedin = contact.get('linkedin') or contact.get('LinkedIn') or ''
                github = contact.get('github') or contact.get('GitHub') or ''
                replacements = {
                    '[Your Full Name]': name,
                    '[Your Name]': name,
                    '[your name]': name,
                    '[Your Contact Information]': ', '.join(filter(None, [email, phone])),
                    '[your email]': email,
                    '[your phone]': phone,
                    '[LinkedIn URL]': linkedin,
                    '[LinkedIn]': linkedin,
                    '[GitHub URL]': github,
                    '[GitHub]': github,
                }
                # Accept additional common placeholder variants
                alt = {
                    '[Candidate Name]': name,
                    '[Email]': email,
                    '[Phone]': phone,
                    '[Your Email]': email,
                    '[Your Phone]': phone,
                    '[Contact]': ', '.join(filter(None, [email, phone])),
                    '[Contact Information]': ', '.join(filter(None, [email, phone])),
                }
                replacements.update(alt)
                s = text
                for k, v in replacements.items():
                    if v:
                        s = s.replace(k, v)
                return s

            # Background generation to avoid long blocking calls that can close WebSocket
            # directory where background results are stored for main thread to pick up
            BG_RESULTS_DIR = os.path.join('app', 'logs', 'bg_results')
            os.makedirs(BG_RESULTS_DIR, exist_ok=True)

            def _background_generate(prompt_text, resume_info_local, job_local, prompt_key):
                try:
                    res = chain.call_llm(prompt_text, trim_to=1600)
                    filled = _fill_placeholders(res or '', resume_info_local or {})
                    try:
                        append_message('assistant', filled)
                    except Exception:
                        pass
                    # write result to a file for the main thread to consume (avoid st.* in background)
                    out_path = os.path.join(BG_RESULTS_DIR, f"{prompt_key}.json")
                    with open(out_path, 'w', encoding='utf-8') as fh:
                        json.dump({'output': filled, 'ts': int(time.time())}, fh, ensure_ascii=False)
                except Exception as e:
                    out_path = os.path.join(BG_RESULTS_DIR, f"{prompt_key}.json")
                    try:
                        with open(out_path, 'w', encoding='utf-8') as fh:
                            json.dump({'error': str(e), 'ts': int(time.time())}, fh, ensure_ascii=False)
                    except Exception:
                        pass

            # Kick off background thread if not already generating
            # create a prompt key used for matching background result files
            prompt_key = hashlib.sha256(full_prompt.encode('utf-8')).hexdigest()
            result_file = os.path.join('app', 'logs', 'bg_results', f"{prompt_key}.json")
            if not st.session_state.get('generating'):
                st.session_state['generating'] = True
                st.session_state.pop('assistant_error', None)
                thread = threading.Thread(target=_background_generate, args=(full_prompt, resume_info, job, prompt_key), daemon=True)
                thread.start()

            # If background result file exists, load it into session_state and remove file
            try:
                if os.path.exists(result_file):
                    with open(result_file, 'r', encoding='utf-8') as fh:
                        j = json.load(fh)
                    try:
                        if 'output' in j:
                            st.session_state['assistant_output'] = j.get('output')
                        if 'error' in j:
                            st.session_state['assistant_error'] = j.get('error')
                    except Exception:
                        pass
                    try:
                        os.remove(result_file)
                    except Exception:
                        pass
                    st.session_state['generating'] = False
            except Exception:
                pass

            # Show progress and final output
            st.subheader(f"Email for: {job.get('role', 'Unknown')}")
            if st.session_state.get('generating'):
                st.info('Generating the email — please keep this page open. This may take up to a minute.')
            if st.session_state.get('assistant_error'):
                st.error('Generation error: ' + st.session_state.get('assistant_error'))
            shown_output = st.session_state.get('assistant_output')
            if shown_output:
                st.code(shown_output, language='markdown')
            elif not st.session_state.get('generating'):
                simple = f"Hello,\n\nI am reaching out regarding the {job.get('role','position')} role. I have experience in {', '.join((resume_info or {}).get('skills') or [])}.\n\nRegards."
                st.code(simple, language='markdown')

            # show poster info if available
            if poster_info.get('contact_email'):
                st.info(f"Contact email found: {poster_info.get('contact_email')}")
            if poster_info.get('poster_profile'):
                st.info(f"Poster profile (LinkedIn): {poster_info.get('poster_profile')}")
        except Exception as e:
            st.error(f"An Error Occurred: {e}")


if __name__ == "__main__":
    st.set_page_config(layout="wide", page_title="Cold Email Generator", page_icon="📧")
    create_streamlit_app(None, clean_text)


