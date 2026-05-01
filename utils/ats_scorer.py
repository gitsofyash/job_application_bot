"""
ATS RESUME SCORING MODULE

Analyzes resume for ATS compatibility and scores it 0-100 based on:
  - Keyword matching with job description (40%)
  - Resume structure & formatting (30%)
  - Content optimization (20%)
  - Skills matching (10%)

Features:
  - Extracts keywords from JD automatically
  - Matches against resume content
  - Checks for proper sections
  - Validates formatting for ATS compatibility
  - Returns detailed score breakdown with recommendations

Usage:
    scorer = ATSScorer()
    score, report = scorer.score_resume(resume_text, jd_text)
"""

import re
import json
from typing import Tuple, Dict, List, Optional
from pathlib import Path
from dataclasses import dataclass
from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class ATSScore:
    """ATS Score Report"""
    total_score: float  # 0-100
    keyword_score: float  # 40%
    structure_score: float  # 30%
    content_score: float  # 20%
    skills_score: float  # 10%
    keywords_found: List[str]
    keywords_missing: List[str]
    issues: List[str]
    recommendations: List[str]


class ATSScorer:
    """Analyze resume for ATS compatibility"""

    def __init__(self):
        self.console = console
        # Common ATS-unfriendly elements
        self.problematic_elements = [
            "image", "pdf_image", "graphic", "chart",
            "table", "text_box", "shape", "special_char",
            "inconsistent_formatting"
        ]

    def score_resume(self, resume_text: str, jd_text: str, resume_file: Optional[str] = None) -> Tuple[float, ATSScore]:
        """
        Score resume against job description.

        Args:
            resume_text: Resume content as plain text or HTML
            jd_text: Job description text
            resume_file: Optional path to resume file for format checking

        Returns:
            Tuple of (total_score, detailed_report)
        """
        # Extract keywords from JD
        jd_keywords = self._extract_keywords(jd_text)

        # Check keyword matching (40% weight)
        keywords_found, keywords_missing = self._match_keywords(resume_text, jd_keywords)
        keyword_score = len(keywords_found) / max(1, len(jd_keywords)) * 100

        # Check structure (25% weight) - reduced from 30%
        structure_score = self._check_structure(resume_text)

        # Check content optimization (20% weight)
        content_score = self._check_content_optimization(resume_text)

        # Check skills section (15% weight) - increased from 10%
        skills_score = self._check_skills_section(resume_text)

        # Calculate weighted total (giving more weight to keywords and skills)
        total_score = (
            keyword_score * 0.40 +
            structure_score * 0.25 +
            content_score * 0.20 +
            skills_score * 0.15
        )

        # Generate issues and recommendations
        issues, recommendations = self._generate_issues_and_recommendations(
            keywords_found, keywords_missing, structure_score, 
            content_score, skills_score, resume_text
        )

        report = ATSScore(
            total_score=round(total_score, 2),
            keyword_score=round(keyword_score, 2),
            structure_score=round(structure_score, 2),
            content_score=round(content_score, 2),
            skills_score=round(skills_score, 2),
            keywords_found=sorted(keywords_found),
            keywords_missing=sorted(keywords_missing),
            issues=issues,
            recommendations=recommendations
        )

        return total_score, report

    def _extract_keywords(self, jd_text: str) -> List[str]:
        """Extract important keywords from job description"""
        jd_lower = jd_text.lower()

        # Technical keywords to extract
        keywords = []

        # Programming languages
        languages = ["python", "golang", "go", "java", "c++", "c#", "javascript", "typescript", "rust", "php", "ruby", "kotlin", "swift", "r"]
        for lang in languages:
            if lang in jd_lower:
                keywords.append(lang)

        # Frameworks & technologies
        frameworks = [
            "react", "vue", "angular", "django", "flask", "spring", "fastapi",
            "aws", "azure", "gcp", "docker", "kubernetes", "kafka", "redis",
            "postgresql", "mysql", "mongodb", "dynamodb", "elasticsearch",
            "lambda", "s3", "ec2", "rds", "iam", "cloudwatch", "api gateway",
            "boto3", "sqlalchemy", "jwt", "oauth", "nginx", "apache",
            "rabbitmq", "celery", "grpc", "protobuf", "graphql",
            "git", "ci/cd", "jenkins", "gitlab", "github actions", 
            "terraform", "ansible", "helm", "linux", "unix", "bash",
            "jira", "slack", "fastapi", "aiohttp", "asyncio", "numpy", "pandas"
        ]
        for framework in frameworks:
            if framework in jd_lower:
                keywords.append(framework)

        # Concepts and skills
        concepts = [
            "rest api", "microservices", "distributed systems", "data structures",
            "algorithms", "system design", "debugging", "logging", "monitoring",
            "test-driven development", "unit testing", "integration testing",
            "scalability", "performance optimization", "security", "authentication",
            "authorization", "database design", "query optimization", "caching",
            "api design", "real-time data processing", "sensor fusion", "embedded systems",
            "can bus", "aspice", "cloud cost optimization", "high availability",
            "disaster recovery", "load balancing", "cdn", "sql injection", 
            "xss prevention", "rate limiting", "circuit breaker", "event-driven"
        ]
        for concept in concepts:
            if concept in jd_lower:
                keywords.append(concept)

        # Soft skills
        soft_skills = [
            "communication", "collaboration", "problem-solving", "attention to detail",
            "team player", "self-motivated", "quick learner", "analytical",
            "mentoring", "leadership", "agile", "scrum"
        ]
        for skill in soft_skills:
            if skill in jd_lower:
                keywords.append(skill)

        return list(set(keywords))  # Remove duplicates

    def _match_keywords(self, resume_text: str, keywords: List[str]) -> Tuple[List[str], List[str]]:
        """Match keywords found in resume"""
        resume_lower = resume_text.lower()
        found = []
        missing = []

        for keyword in keywords:
            keyword_lower = keyword.lower()
            aliases = {
                "golang": ["golang", "go", "golang"],
                "go": ["golang", "go"],
                "rest api": ["rest api", "rest apis", "restful", "rest services"],
                "lambda": ["lambda", "aws lambda", "serverless"],
                "s3": ["s3", "aws s3", "simple storage service"],
                "ec2": ["ec2", "aws ec2", "elastic compute"],
                "rds": ["rds", "aws rds", "relational database"],
                "dynamodb": ["dynamodb", "aws dynamodb"],
                "api gateway": ["api gateway", "aws api gateway"],
                "iam": ["iam", "aws iam", "identity and access"],
                "cloudwatch": ["cloudwatch", "aws cloudwatch", "monitoring"],
                "monitoring": ["monitoring", "monitor", "cloudwatch", "observability", "logs", "logging"],
                "kafka": ["kafka", "apache kafka", "event streaming"],
                "test-driven development": ["test-driven development", "tdd"],
                "unit testing": ["unit testing", "unit tests", "test suite", "code coverage", "unity framework"],
                "ci/cd": ["ci/cd", "pipeline", "github actions", "continuous integration", "continuous deployment", "jenkins"],
                "system design": ["system design", "system architecture", "architectural design", "scalable systems"],
                "microservices": ["microservices", "micro-services", "microservice architecture"],
                "database design": ["database design", "sql design", "schema design"],
                "caching": ["caching", "cache strategy", "redis cache", "cache management"],
                "authentication": ["authentication", "oauth", "jwt", "auth"],
                "authorization": ["authorization", "rbac", "access control"],
                "api design": ["api design", "api development", "rest design"],
                "docker": ["docker", "containerization", "container"],
                "kubernetes": ["kubernetes", "k8s", "container orchestration"],
                "agile": ["agile", "scrum", "kanban", "sprint", "agile methodology"],
                "communication": ["communication", "collaboration", "teamwork", "cross-functional"],
                "algorithms": ["algorithms", "algorithm optimization"],
                "data structures": ["data structures", "data structure"],
                "distributed systems": ["distributed systems", "distributed architecture", "distributed computing"],
                "event-driven": ["event-driven", "event-driven architecture", "event streaming"],
                "apache": ["apache", "apache kafka", "apache server"],
                "angular": ["angular", "angular js"],
                "logging": ["logging", "logs", "centralized logging", "log aggregation"],
                "scalability": ["scalability", "scalable", "scaling"],
                "performance optimization": ["performance", "optimization", "optimize"],
                "security": ["security", "secure", "security practices"],
                "testing": ["testing", "test", "test automation"],
                "database": ["database", "sql", "nosql"],
                "cache": ["cache", "caching", "redis"],
                "api": ["api", "apis"],
                "microservice": ["microservices", "microservice"],
                "cloud": ["cloud", "aws", "azure", "gcp"],
            }.get(keyword_lower, [keyword_lower])

            if any(alias in resume_lower for alias in aliases):
                found.append(keyword)
            else:
                missing.append(keyword)

        return found, missing

    def _check_structure(self, resume_text: str) -> float:
        """Check if resume has proper ATS-friendly structure"""
        score = 100
        resume_lower = resume_text.lower()

        # Required sections
        required_sections = {
            "contact": ["email", "phone", "address", "linkedin", "github"],
            "summary": ["summary", "profile", "objective"],
            "experience": ["experience", "work", "employment"],
            "education": ["education", "degree", "university", "college"],
            "skills": ["skills", "technical", "programming"]
        }

        sections_found = 0
        for section, keywords in required_sections.items():
            if any(kw in resume_lower for kw in keywords):
                sections_found += 1
            else:
                score -= 15

        # Check for problematic elements
        problematic_patterns = [
            r"<img|image",
            r"<table|colspan|rowspan",
            r"[^\w\s&\-]",  # Special characters beyond standard
        ]

        for pattern in problematic_patterns:
            if re.search(pattern, resume_text, re.IGNORECASE):
                score -= 5

        # Check line length consistency (ATS prefers < 100 chars)
        lines = resume_text.split('\n')
        long_lines = sum(1 for line in lines if len(line) > 120)
        if long_lines > len(lines) * 0.3:
            score -= 10

        return max(0, min(100, score))

    def _check_content_optimization(self, resume_text: str) -> float:
        """Check content for ATS optimization"""
        score = 100

        # Check for action verbs
        action_verbs = [
            "developed", "designed", "implemented", "architected", "built",
            "optimized", "improved", "created", "engineered", "deployed",
            "managed", "led", "coordinated", "analyzed", "solved", "enhanced",
            "accelerated", "boosted", "reduced", "increased", "achieved",
            "established", "initiated", "modernized", "refactored"
        ]
        action_count = sum(1 for verb in action_verbs if verb in resume_text.lower())

        if action_count < 3:
            score -= 20
        elif action_count < 6:
            score -= 10
        elif action_count >= 10:
            score += 5  # Bonus for plenty of action verbs

        # Check for quantifiable results (very important for ATS)
        quantifiable_matches = re.findall(r'\d+%|\d+x|\$\d+|(\d{1,3},?\d{3,})\+?|\d+\s*(hours|days|weeks|months|years|users|requests|transactions|improvements)', resume_text)
        
        if len(quantifiable_matches) == 0:
            score -= 20
        elif len(quantifiable_matches) < 3:
            score -= 10
        elif len(quantifiable_matches) >= 5:
            score += 10  # Bonus for multiple quantifiable results

        # Check for proper date formatting
        if not re.search(r'\d{4}|\w+\s+\d{4}|20\d{2}', resume_text):
            score -= 10
        else:
            # Bonus for good date formatting
            score += 5

        # Check for consistent formatting
        periods_count = resume_text.count('.')
        commas_count = resume_text.count(',')

        if periods_count == 0 or commas_count == 0:
            score -= 15
        else:
            score += 3  # Bonus for proper punctuation

        # Check for white space efficiency (no excessive blank lines)
        blank_lines = len([line for line in resume_text.split('\n') if not line.strip()])
        total_lines = len(resume_text.split('\n'))

        if total_lines > 0:
            blank_ratio = blank_lines / total_lines
            if blank_ratio > 0.25:
                score -= 10
            elif blank_ratio < 0.10:
                score += 5  # Bonus for efficient use of space

        # Check for page length (1 page = ~250-450 words for ATS)
        word_count = len(resume_text.split())
        if word_count > 700:
            score -= 15  # Too long
        elif word_count > 500:
            score -= 5  # Slightly long
        elif word_count >= 300:
            score += 10  # Good word count
        elif word_count < 150:
            score -= 10  # Too short

        return max(0, min(100, score))

    def _check_skills_section(self, resume_text: str) -> float:
        """Check if skills section is properly formatted"""
        score = 100

        if "skills" not in resume_text.lower():
            return 30  # Major issue: no skills section

        # Find skills section
        skills_match = re.search(
            r'skills?[:\n]+(.*?)(?=\n\n|\n[A-Z]|$)',
            resume_text,
            re.IGNORECASE | re.DOTALL
        )

        if not skills_match:
            return 50

        skills_section = skills_match.group(1)

        # Count number of skills listed
        skill_items = len(re.split(r'[,;•\n-]', skills_section))

        if skill_items < 5:
            score -= 30
        elif skill_items < 10:
            score -= 15

        # Check for proper categorization
        if any(cat in skills_section.lower() for cat in ["language", "framework", "tool", "category"]):
            score += 10

        return max(0, min(100, score))

    def _generate_issues_and_recommendations(
        self, keywords_found: List[str], keywords_missing: List[str],
        structure_score: float, content_score: float, skills_score: float,
        resume_text: str
    ) -> Tuple[List[str], List[str]]:
        """Generate issues and recommendations"""
        issues = []
        recommendations = []

        # Keyword issues
        if len(keywords_missing) > len(keywords_found):
            issues.append(f"Missing {len(keywords_missing)} important keywords from JD")
            for kw in keywords_missing[:5]:  # Show top 5
                recommendations.append(f"Add '{kw}' to your resume")

        # Structure issues
        if structure_score < 70:
            issues.append("Resume structure may not be ATS-friendly")
            recommendations.append("Ensure all standard sections present: Contact, Summary, Experience, Education, Skills")

        # Content issues
        if content_score < 70:
            issues.append("Content could be better optimized for ATS")
            recommendations.append("Use more action verbs (developed, designed, implemented, etc.)")
            recommendations.append("Add quantifiable results (numbers, percentages, metrics)")

        # Skills issues
        if skills_score < 70:
            issues.append("Skills section needs improvement")
            recommendations.append("Create a dedicated Skills section with categorized skills")
            recommendations.append("List technical skills, frameworks, tools, and soft skills separately")

        # Formatting issues
        if resume_text.count('\n') > 50:
            issues.append("Resume may be too long for single page")
            recommendations.append("Trim content to ensure single-page format")

        return issues, recommendations

    def print_report(self, score: ATSScore) -> None:
        """Print formatted ATS score report"""
        console.print("\n" + "=" * 70, style="bold cyan")
        console.print("ATS RESUME SCORE REPORT", justify="center", style="bold cyan")
        console.print("=" * 70 + "\n", style="bold cyan")

        # Overall score
        overall_color = "green" if score.total_score >= 90 else "yellow" if score.total_score >= 70 else "red"
        console.print(f"[bold {overall_color}]OVERALL ATS SCORE: {score.total_score}/100[/bold {overall_color}]")

        # Score breakdown table
        table = Table(title="Score Breakdown", show_header=True, header_style="bold")
        table.add_column("Category", style="cyan")
        table.add_column("Score", style="magenta")
        table.add_column("Weight", style="blue")

        table.add_row("Keyword Matching", f"{score.keyword_score}/100", "40%")
        table.add_row("Structure & Format", f"{score.structure_score}/100", "30%")
        table.add_row("Content Optimization", f"{score.content_score}/100", "20%")
        table.add_row("Skills Section", f"{score.skills_score}/100", "10%")

        console.print(table)

        # Keywords found
        console.print(f"\n[bold green]✓ Keywords Found ({len(score.keywords_found)}):[/bold green]")
        for kw in score.keywords_found[:10]:
            console.print(f"  • {kw}")
        if len(score.keywords_found) > 10:
            console.print(f"  ... and {len(score.keywords_found) - 10} more")

        # Keywords missing
        if score.keywords_missing:
            console.print(f"\n[bold red]✗ Keywords Missing ({len(score.keywords_missing)}):[/bold red]")
            for kw in score.keywords_missing[:10]:
                console.print(f"  • {kw}")
            if len(score.keywords_missing) > 10:
                console.print(f"  ... and {len(score.keywords_missing) - 10} more")

        # Issues
        if score.issues:
            console.print(f"\n[bold yellow]⚠ Issues Found:[/bold yellow]")
            for issue in score.issues:
                console.print(f"  • {issue}")

        # Recommendations
        if score.recommendations:
            console.print(f"\n[bold cyan]💡 Recommendations:[/bold cyan]")
            for i, rec in enumerate(score.recommendations, 1):
                console.print(f"  {i}. {rec}")

        console.print("\n" + "=" * 70 + "\n", style="bold cyan")


# Convenience functions
def score_resume_files(resume_path: str, jd_path: str) -> Tuple[float, ATSScore]:
    """Score resume from file paths"""
    with open(resume_path, 'r') as f:
        resume_text = f.read()
    with open(jd_path, 'r') as f:
        jd_text = f.read()

    scorer = ATSScorer()
    return scorer.score_resume(resume_text, jd_text, resume_path)


if __name__ == "__main__":
    # Example usage
    sample_resume = """
    YASH GUPTA
    Email: yash@example.com | Phone: +91-9876543210
    LinkedIn: linkedin.com/in/yash | GitHub: github.com/yash

    PROFESSIONAL SUMMARY
    Backend Software Engineer with 3+ years of experience in building scalable APIs,
    cloud architecture, and data processing pipelines.

    TECHNICAL SKILLS
    Languages: Python, Golang, C++, JavaScript
    Frameworks: Flask, Django, FastAPI
    Databases: PostgreSQL, MongoDB, Redis
    Cloud: AWS (EC2, S3, Lambda, DynamoDB)
    Tools: Docker, Git, Kubernetes

    EXPERIENCE
    Senior Backend Engineer, Tech Corp (2023-Present)
    - Developed REST APIs in Python and Golang processing 10,000 req/sec
    - Optimized database queries reducing latency by 70%
    - Implemented CI/CD pipeline using Docker and GitHub Actions

    EDUCATION
    B.Tech Computer Science, XYZ University (2021)
    """

    sample_jd = """
    Backend SDE 1 - Golang
    We're looking for a Backend Software Engineer with experience in:
    - Golang programming language
    - REST API development
    - Microservices architecture
    - Database design and optimization
    - AWS cloud services
    - Docker containerization
    - Data structures and algorithms
    - System design and scalability
    - Debugging and monitoring tools
    """

    scorer = ATSScorer()
    score, report = scorer.score_resume(sample_resume, sample_jd)
    scorer.print_report(report)
