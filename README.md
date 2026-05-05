# 🤖 Job Application Automation Bot

An intelligent automation tool that streamlines the job application process by automatically extracting job descriptions, tailoring resumes, generating ATS-optimized PDFs, creating targeted cover letters, and optionally auto-filling job application forms.

---

## 🎯 Features

- **Job Description Extraction**: Automatically extract structured data from job postings using web scraping
- **Resume Tailoring**: Intelligently tailor your resume to match specific job descriptions using LLM
- **ATS Optimization**: Generate ATS-friendly resumes with proper formatting and keyword optimization
- **PDF Generation**: Create professional, company-specific PDF resumes (strict 1-page format)
- **Cover Letter Generation**: Automatically generate tailored cover letters based on job requirements
- **Multi-LLM Support**: Works with multiple LLM providers (Cohere, OpenAI, Anthropic, Ollama, Google Gemini)
- **Company-Based File Management**: Automatically organize outputs by company name with no file overwrites
- **Dry-Run Mode**: Test the entire pipeline without generating output files
- **Batch Job Search**: Discover job postings from RSS feeds and auto-apply to multiple positions

---

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- Virtual environment (recommended)
- API keys for your chosen LLM provider

### Installation

1. **Clone or navigate to the project directory**
   ```bash
   cd job_application_bot
   ```

2. **Create and activate a virtual environment**
   ```bash
   # Windows
   python -m venv venv
   venv\Scripts\activate
   
   # macOS/Linux
   python -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   Create a `.env` file in the root directory:
   ```env
   # LLM Configuration
   LLM_PROVIDER=COHERE          # Options: COHERE, OPENAI, ANTHROPIC, OLLAMA, GOOGLE
   COHERE_API_KEY=your_key_here
   OPENAI_API_KEY=your_key_here
   ANTHROPIC_API_KEY=your_key_here
   GOOGLE_API_KEY=your_key_here
   
   # Optional Settings
   DEBUG=false
   HEADLESS=true               # Show browser window
   DRY_RUN=false              # Test without generating files
   ```

---

## 📖 Usage

### Basic Job Application Automation

Apply to a single job by providing a job posting URL:

```bash
python main.py --url "https://jobs.example.com/job/123"
```

### Dry-Run Mode

Test the entire pipeline without creating output files:

```bash
python main.py --url "https://jobs.example.com/job/123" --dry-run
```

### Output

The bot generates:
- `output/{company}/resume_{company}.pdf` - Tailored resume
- `output/{company}/cover_letter_{company}.html` - Tailored cover letter
- `output/{company}/extracted_job_description.json` - Structured job data

---

## 📁 Project Structure

```
job_application_bot/
├── main.py                 # Main entry point and orchestrator
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (create this)
│
├── config/
│   ├── __init__.py
│   └── settings.py        # Global configuration and settings
│
├── modules/               # Core processing modules
│   ├── m1_extractor.py    # Extract job descriptions from URLs
│   ├── m2_tailor.py       # Tailor resume to job description
│   ├── m2_5_gap_filler.py # Fill skills gaps
│   ├── m3_generator.py    # Generate PDF resumes
│   ├── m4_apply.py        # Auto-fill and submit applications
│   ├── m5_coverletter.py  # Generate cover letters
│   ├── m6_gemini_polish.py # Polish with Gemini API
│   ├── m7_latex_resume.py # Generate LaTeX resumes
│   └── m8_job_search.py   # Search and batch apply
│
├── utils/                 # Utility functions
│   ├── ats_scorer.py      # ATS compatibility scoring
│   └── url_parser.py      # URL parsing utilities
│
├── data/                  # Data files
│   ├── base_resume.json   # Your base resume template
│   └── user_profile.json  # Your profile information
│
├── templates/             # HTML/Jinja2 templates
│   ├── resume.html        # Resume template
│   ├── resume_ats.html    # ATS-optimized resume template
│   └── cover_letter.html  # Cover letter template
│
├── output/                # Generated documents (auto-created)
│   └── {company}/
│       ├── resume_{company}.pdf
│       ├── cover_letter_{company}.html
│       └── extracted_job_description.json
│
└── extra/                 # Documentation and tests
    ├── docs/             # Comprehensive guides and reports
    ├── setup_scripts/    # Setup automation scripts
    └── tests/            # Test suite
```

---

## 🔧 Configuration

### Environment Variables

| Variable | Options | Default | Description |
|----------|---------|---------|-------------|
| `LLM_PROVIDER` | COHERE, OPENAI, ANTHROPIC, OLLAMA, GOOGLE | COHERE | LLM backend to use |
| `DEBUG` | true, false | false | Enable verbose logging |
| `DRY_RUN` | true, false | false | Test mode without file generation |
| `HEADLESS` | true, false | true | Run browser in headless mode |
| `RESUME_TAILOR_USE_LLM` | true, false | true | Use LLM for resume tailoring |
| `COVER_LETTER_USE_LLM` | true, false | true | Use LLM for cover letter generation |
| `ENABLE_GEMINI_POLISH` | true, false | false | Enable Gemini polish post-processing |

### LLM Provider Configuration

**Cohere** (Recommended - Default)
```env
LLM_PROVIDER=COHERE
COHERE_API_KEY=your_cohere_key
```

**OpenAI**
```env
LLM_PROVIDER=OPENAI
OPENAI_API_KEY=your_openai_key
```

**Anthropic**
```env
LLM_PROVIDER=ANTHROPIC
ANTHROPIC_API_KEY=your_anthropic_key
```

**Local Ollama**
```env
LLM_PROVIDER=OLLAMA
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama2
```

**Google Gemini**
```env
LLM_PROVIDER=GOOGLE
GOOGLE_API_KEY=your_google_key
```

---

## 📋 Core Modules

### Module 1: Job Description Extractor (`m1_extractor.py`)
Automatically extracts and structures job posting information:
- Job title, company, location
- Key responsibilities
- Required and preferred qualifications
- Salary information (if available)

### Module 2: Resume Tailor (`m2_tailor.py`)
Intelligently customizes your base resume:
- Maps your skills to job requirements
- Highlights relevant experience
- Optimizes keyword density for ATS
- Maintains professional formatting

### Module 3: PDF Generator (`m3_generator.py`)
Creates professional, ATS-friendly PDFs:
- 1-page strict format enforcement
- Proper character encoding
- Company-specific naming
- Professional typography

### Module 4: Application Auto-Filler (`m4_apply.py`)
Automatically fills and submits application forms:
- Form field detection
- Auto-population with candidate data
- Optional form submission

### Module 5: Cover Letter Generator (`m5_coverletter.py`)
Generates targeted cover letters:
- Company and role-specific content
- Professional tone and structure
- Company name extraction

### Module 6: Gemini Polish (`m6_gemini_polish.py`)
Optional post-processing with Google Gemini API:
- Content enhancement
- Grammar and style refinement
- Additional optimization

### Module 7: LaTeX Resume (`m7_latex_resume.py`)
Generate resumes in LaTeX format:
- Advanced formatting control
- Publication-quality output
- Customizable styling

### Module 8: Job Search (`m8_job_search.py`)
Batch job discovery and application:
- RSS feed parsing
- Job posting aggregation
- Automated batch applications

---

## 🛠️ Utilities

### ATS Scorer (`utils/ats_scorer.py`)
Analyzes resume ATS compatibility:
- Keyword density analysis
- Formatting score
- Structural assessment
- Optimization recommendations

### URL Parser (`utils/url_parser.py`)
Parses job posting URLs:
- Extracts company information
- Validates URL format
- Handles various job board formats

---

## 📊 Data Formats

### Base Resume (`data/base_resume.json`)
Your foundational resume in JSON format:
```json
{
  "personal_info": {
    "name": "Your Name",
    "email": "your.email@example.com",
    "phone": "123-456-7890"
  },
  "experience": [...],
  "skills": [...],
  "education": [...]
}
```

### User Profile (`data/user_profile.json`)
Career goals and preferences:
```json
{
  "target_roles": [...],
  "industries": [...],
  "preferences": {...}
}
```

---

## 🎓 Example Workflow

1. **Find a job posting**: Copy the job posting URL
2. **Run the bot**: 
   ```bash
   python main.py --url "https://jobs.example.com/123"
   ```
3. **Review generated files** in the `output/{company}/` directory
4. **Submit application** with generated resume and cover letter

---

## 🔍 Troubleshooting

### Common Issues

**"API Key not found"**
- Ensure `.env` file exists in the root directory
- Verify API key is correctly set for your LLM provider

**"Module not found"**
- Activate virtual environment: `source venv/bin/activate` (macOS/Linux) or `venv\Scripts\activate` (Windows)
- Reinstall dependencies: `pip install -r requirements.txt`

**"Browser timeout"**
- Try with `HEADLESS=false` to see what's happening
- Increase timeout in config settings
- Check internet connection

**ATS Score is Low**
- Review extracted keywords from job description
- Ensure base resume has relevant keywords
- Check template formatting

---

## 📚 Documentation

For more detailed information, see the documentation in `extra/docs/`:
- `ATS_90_PLUS_STRATEGY.md` - Advanced ATS optimization
- `RESUME_CONTENT_OPTIMIZATION.md` - Content improvement guide
- `ENHANCEMENT_REPORT.md` - Feature enhancements
- `README.md` - Additional guides

---

## 🧪 Testing

Run the test suite:
```bash
python -m pytest extra/tests/test_enhancements.py -v
```

---

## 🤝 Contributing

Contributions are welcome! Please:
1. Test thoroughly before submitting
2. Follow existing code style
3. Document new features
4. Update relevant documentation

---

## ⚖️ Legal & Ethical Considerations

This bot is designed for personal job application automation. Users should:
- Respect website terms of service
- Ensure compliance with local laws and regulations
- Use ethically and responsibly
- Maintain authenticity in applications
- Respect robots.txt and rate limiting

---

## 📝 License

This project is provided as-is for personal use.

---

## 🎯 Future Enhancements

- [ ] Multi-threading for batch applications
- [ ] Database for tracking applications
- [ ] LinkedIn integration
- [ ] Email notification system
- [ ] Advanced analytics dashboard
- [ ] Interview preparation module
- [ ] Salary negotiation assistant

---

## 📧 Support

For issues, questions, or suggestions, please refer to the documentation in `extra/docs/` or review the configuration settings in `config/settings.py`.

---

**Happy job hunting! 🚀**
