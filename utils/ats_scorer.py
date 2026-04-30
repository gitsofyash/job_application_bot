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

        # Check structure (30% weight)
        structure_score = self._check_structure(resume_text)

        # Check content optimization (20% weight)
        content_score = self._check_content_optimization(resume_text)

        # Check skills section (10% weight)
        skills_score = self._check_skills_section(resume_text)

        # Calculate weighted total
        total_score = (
            keyword_score * 0.40 +
            structure_score * 0.30 +
            content_score * 0.20 +
            skills_score * 0.10
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
        languages = ["python", "golang", "go", "java", "c++", "c#", "javascript", "typescript", "rust", "php", "ruby"]
        for lang in languages:
            if lang in jd_lower:
                keywords.append(lang)

        # Frameworks & technologies
        frameworks = [
            "react", "vue", "angular", "django", "flask", "spring", "fastapi",
            "aws", "azure", "gcp", "docker", "kubernetes", "kafka", "redis",
            "postgresql", "mysql", "mongodb", "dynamodb", "elasticsearch",
            "lambda", "s3", "ec2", "rds", "api gateway", "iam", "cloudwatch",
            "boto3", "sqlalchemy", "jwt",
            "git", "ci/cd", "jenkins", "terraform", "linux", "unix"
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
            "can bus", "aspice", "cloud cost optimization"
        ]
        for concept in concepts:
            if concept in jd_lower:
                keywords.append(concept)

        # Soft skills
        soft_skills = [
            "communication", "collaboration", "problem-solving", "attention to detail",
            "team player", "self-motivated", "quick learner", "analytical"
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
                "golang": ["golang", "go"],
                "go": ["golang", "go"],
                "rest api": ["rest api", "rest apis", "restful"],
                "lambda": ["lambda", "aws lambda"],
                "s3": ["s3", "aws s3"],
                "ec2": ["ec2", "aws ec2"],
                "rds": ["rds", "aws rds"],
                "dynamodb": ["dynamodb", "aws dynamodb"],
                "api gateway": ["api gateway", "aws api gateway"],
                "iam": ["iam", "aws iam"],
                "cloudwatch": ["cloudwatch", "aws cloudwatch"],
                "monitoring": ["monitoring", "monitor", "cloudwatch", "observability"],
                "kafka": ["kafka", "apache kafka"],
                "test-driven development": ["test-driven development", "tdd"],
                "unit testing": ["unit testing", "unit tests", "test suite", "code coverage", "unity framework"],
                "ci/cd": ["ci/cd", "pipeline", "github actions"],
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
            "managed", "led", "coordinated", "analyzed", "solved"
        ]
        action_count = sum(1 for verb in action_verbs if verb in resume_text.lower())

        if action_count < 5:
            score -= 20
        elif action_count < 10:
            score -= 10

        # Check for quantifiable results
        if not re.search(r'\d+%|\d+x|\$\d+|(\d+,?\d+)\+', resume_text):
            score -= 15

        # Check for proper date formatting
        if not re.search(r'\d{4}|\w+\s+\d{4}|20\d{2}', resume_text):
            score -= 10

        # Check for consistent formatting
        periods_count = resume_text.count('.')
        commas_count = resume_text.count(',')
        hyphens_count = resume_text.count('-')

        if periods_count == 0 or commas_count == 0:
            score -= 15

        # Check for white space efficiency (no excessive blank lines)
        blank_lines = len([line for line in resume_text.split('\n') if not line.strip()])
        total_lines = len(resume_text.split('\n'))

        if blank_lines > total_lines * 0.2:
            score -= 10

        # Check for page length (1 page = ~250-400 words for one page)
        word_count = len(resume_text.split())
        if word_count > 600:
            score -= 10  # Too long
        elif word_count < 200:
            score -= 5  # Too short

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
