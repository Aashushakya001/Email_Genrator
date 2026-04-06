# 🚀 AI Cold Email Generator (Streamlit-Based)

An AI-powered application that generates **personalized job application emails** using a candidate’s resume and job description.

Built with a **modular pipeline architecture**, this project focuses on **cost optimization, caching, and efficient LLM usage** while maintaining a clean and extensible codebase.

---

## 🧠 Key Features

* 📄 Resume Parsing (stored for reuse)
* 🌐 Job URL Fetching & Extraction
* ✉️ AI Cold Email Generation (Azure OpenAI)
* ⚡ Smart Caching (avoid repeated LLM calls)
* 🧩 Modular Pipeline Design
* 🖥️ Interactive UI using Streamlit

---

## 🏗️ Current Architecture

```text
Streamlit UI
    ↓
Pipeline Logic (modular Python files)
    ↓
Local Storage (cache + resumes + data)
    ↓
Azure OpenAI (LLM)
```

---

## 📁 Project Structure

```text
app/
│
├── main.py                     # Streamlit entry point
├── chains.py                   # LangChain pipelines
├── cache.py                    # Caching logic
├── chat_memory.py              # Chat/session memory
│
├── job_extract_and_email.py    # Main pipeline logic
├── job_extract_via_chain.py    # LLM-based extraction
├── job_page_fetch_and_*.py     # Job scraping logic
│
├── resume_parser.py            # Resume parsing
├── utils.py                    # Helper functions
│
├── background.py               # Background processing
├── check_env.py                # Environment validation
│
├── cache/                      # Cached responses (hashed)
├── resumes/                    # Stored resume data
├── data/                       # Intermediate data
├── logs/                       # Logs
│
├── final_result.json
├── final_result_llm.json
└── tmp_resume_text.txt
```

---

## ⚙️ Tech Stack

* **Frontend:** Streamlit
* **Backend Logic:** Python (modular)
* **LLM:** Azure OpenAI
* **Framework:** LangChain
* **Scraping:** Requests + BeautifulSoup
* **Caching:** Local file-based (hash-based)

---

## 🚀 Setup Instructions

### 1️⃣ Create Environment

```bash
conda create -n cold_email python=3.12
conda activate cold_email
```

---

### 2️⃣ Install Dependencies

```bash
pip install langchain langchain-openai openai python-dotenv streamlit requests beautifulsoup4 lxml
```

---

### 3️⃣ Set Environment Variables

Create `.env` file:

```env
AZURE_OPENAI_API_KEY=your_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
```

---

### 4️⃣ Run Application

```bash
streamlit run main.py
```

---

## 🔍 Job Extraction Strategy

The system uses a **multi-step approach**:

```text
1. Fetch job URL (requests)
2. Extract raw text (BeautifulSoup)
3. Apply rule-based parsing (regex + keywords)
4. Optional LLM extraction (only if needed)
```

---

## ⚡ Caching Strategy

* Uses **hash-based file caching**
* Prevents repeated LLM calls
* Stores:

  * Job extraction results
  * Generated emails
  * Intermediate outputs

```text
Input → Hash → Cached JSON
```

---

## 💡 Cost Optimization

* ❌ No LLM for resume parsing
* ❌ No LLM for basic job extraction
* ✅ LLM used only for email generation
* ⚡ Cache prevents redundant API calls
* 📉 Reduced token usage via preprocessing

---

## 🔄 Workflow

```text
User Input (Resume + Job URL)
        ↓
Resume Parsed & Stored
        ↓
Job Description Extracted
        ↓
Relevant Data Prepared
        ↓
LLM Generates Email
        ↓
Result Cached & Displayed
```

---

## ⚠️ Limitations

* Some job sites (LinkedIn, Google Jobs) may block scraping
* JavaScript-heavy pages may require browser-based scraping (future improvement)
* Contact details may not always be available

---

## 🔮 Future Improvements

* 🌐 Playwright integration (dynamic scraping)
* 🧑 User authentication & database storage
* 📊 Dashboard & analytics
* 📬 Email sending integration
* 🧠 Smarter skill matching

---

## 🧠 Learning Outcomes

* Modular AI pipeline design
* Cost-efficient LLM usage
* Real-world scraping strategies
* Caching mechanisms for AI systems
* Streamlit-based rapid prototyping

---

## 👨‍💻 Author

Ayush Shakya

---

## ⭐ Contribution

Feel free to fork, improve, and raise pull requests!

---
