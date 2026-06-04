# Profile Customization Guide

The bot builds resumes from JSON files. Keep these files accurate because generated resumes, cover letters, ATS scoring, and profile Q&A all depend on them.

## Main Files

| File | What It Controls |
|---|---|
| `data/base_resume.json` | Resume content: summary, education, experience, projects, achievements, certifications, skills. |
| `data/user_profile.json` | Personal info, target roles, current employment flags, form mappings, location preferences. |

## Personal Information

Update these fields in both files when sharing with another person:

```json
{
  "name": "Candidate Name",
  "email": "candidate@example.com",
  "phone": "+91 ...",
  "linkedin": "linkedin/candidate",
  "github": "github/candidate"
}
```

## Current Employment

Use `currently_employed` truthfully.

Currently employed:

```json
{
  "currently_employed": true,
  "form_field_mappings": {
    "current_company": "Company Name",
    "current_title": "Software Engineer"
  }
}
```

Not currently employed:

```json
{
  "currently_employed": false,
  "form_field_mappings": {
    "current_company": "",
    "current_title": "Software Engineer"
  }
}
```

## Experience

Keep each role truthful and concise. Recommended format:

```json
{
  "title": "Software Engineer",
  "company": "Company Name",
  "location": "City",
  "duration": "Mar 2026 - Present",
  "type": "Full-Time",
  "bullets": [
    "Built backend services with REST API design and data-processing pipelines for production applications",
    "Designed containerized microservices using Docker and Git-based CI/CD workflows",
    "Contributed to architecture discussions, reusable service components, and technical documentation"
  ]
}
```

Use 2-3 bullets per experience when the resume must remain one page.

## Summary

The current summary style is optimized for software/product/MNC roles:

```text
Software Engineer with strong foundations in DSA, system design, and backend/cloud engineering. Builds scalable APIs and data pipelines using Python, C++, JavaScript, SQL, AWS, Docker, Kafka, PostgreSQL, testing, and monitoring.
```

Avoid:

- Mentioning internship level in the summary.
- Mentioning current company in the summary.
- Claiming senior/staff/lead experience unless true.
- Adding tools that are not supported elsewhere in the resume.

## Skills

Keep skills grouped and truthful:

- Languages
- Backend
- Cloud
- Databases
- Tools
- Frameworks
- Domains
- Methodologies

If a JD asks for a skill not present in the base resume, the bot should treat it as a gap unless there is real supporting evidence.

## Projects

For MNC/software roles, prioritize projects that show:

- Scalable APIs
- Distributed systems
- Cloud architecture
- Databases and indexing
- Monitoring and debugging
- Security and authentication
- Testing and reliability
- Performance optimization
- AI/RAG/ML only when relevant to the JD

## Gap Projects

Gap projects only run when the JD is very different from the saved resume. They should be treated as independent learning and reviewed before being used in a real application.

Do not use a generated project as proof of professional experience unless it was actually completed.

## Quality Checklist

Before sending a generated resume:

- The summary is two clean professional sentences.
- Both current role and internship are visible if relevant.
- Each experience has 2-3 strong bullets.
- No bullet ends mid-sentence.
- No fake seniority is present.
- Skills match real experience or projects.
- The generated PDF is one page and readable.
