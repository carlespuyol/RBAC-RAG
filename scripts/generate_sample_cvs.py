"""
Generate 3 synthetic CV PDFs for SecureRAG testing.
Each CV covers a distinct candidate profile and collectively maps content
to all RBAC subcategories in the information model.

Usage:
    cd securerag
    .venv/Scripts/python scripts/generate_sample_cvs.py
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

OUTPUT_DIR = Path(__file__).parents[1] / "data" / "sample_cvs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Layout constants
PAGE_W, PAGE_H = 595, 842          # A4
MARGIN_L, MARGIN_R = 60, 60
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R
LINE_H_BODY = 14
LINE_H_HEAD = 20
FONT_NAME = "helv"
FONT_NAME_BOLD = "hebo"
COLOR_BLACK = (0, 0, 0)
COLOR_GRAY = (0.4, 0.4, 0.4)
COLOR_ACCENT = (0.1, 0.2, 0.5)


def new_doc() -> tuple[fitz.Document, fitz.Page, float]:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    return doc, page, 60.0  # doc, page, cursor_y


def maybe_new_page(doc: fitz.Document, page: fitz.Page, y: float, needed: float = 30) -> tuple[fitz.Page, float]:
    if y + needed > PAGE_H - 60:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        y = 60.0
    return page, y


def write_text(
    page: fitz.Page,
    x: float,
    y: float,
    text: str,
    fontsize: float = 10,
    bold: bool = False,
    color: tuple = COLOR_BLACK,
) -> None:
    page.insert_text(
        (x, y),
        text,
        fontsize=fontsize,
        fontname=FONT_NAME_BOLD if bold else FONT_NAME,
        color=color,
    )


def draw_line(page: fitz.Page, y: float, color: tuple = COLOR_ACCENT) -> None:
    page.draw_line(
        fitz.Point(MARGIN_L, y),
        fitz.Point(PAGE_W - MARGIN_R, y),
        color=color,
        width=0.8,
    )


def header(page: fitz.Page, name: str, title: str, y: float) -> float:
    write_text(page, MARGIN_L, y, name, fontsize=22, bold=True, color=COLOR_ACCENT)
    y += 26
    write_text(page, MARGIN_L, y, title, fontsize=13, color=COLOR_GRAY)
    y += 18
    draw_line(page, y)
    return y + 10


def section_heading(
    doc: fitz.Document, page: fitz.Page, y: float, title: str
) -> tuple[fitz.Page, float]:
    page, y = maybe_new_page(doc, page, y, needed=LINE_H_HEAD + 10)
    y += 6
    write_text(page, MARGIN_L, y, title.upper(), fontsize=11, bold=True, color=COLOR_ACCENT)
    y += 4
    draw_line(page, y, color=(0.7, 0.7, 0.7))
    y += 10
    return page, y


def body_lines(
    doc: fitz.Document,
    page: fitz.Page,
    y: float,
    lines: list[str],
    indent: float = 0,
    bold_first: bool = False,
) -> tuple[fitz.Page, float]:
    for i, line in enumerate(lines):
        page, y = maybe_new_page(doc, page, y, needed=LINE_H_BODY)
        bold = bold_first and i == 0
        write_text(page, MARGIN_L + indent, y, line, fontsize=10, bold=bold)
        y += LINE_H_BODY
    return page, y


def bullet_lines(
    doc: fitz.Document,
    page: fitz.Page,
    y: float,
    lines: list[str],
) -> tuple[fitz.Page, float]:
    for line in lines:
        page, y = maybe_new_page(doc, page, y, needed=LINE_H_BODY)
        write_text(page, MARGIN_L + 4, y, f"•  {line}", fontsize=10)
        y += LINE_H_BODY
    return page, y


# ──────────────────────────────────────────────────────────────
# CV 1: Alice Johnson — Senior Security Engineer
# ──────────────────────────────────────────────────────────────
def generate_alice() -> Path:
    doc, page, y = new_doc()

    # Header
    y = header(page, "Alice Johnson", "Senior Security Engineer", y)

    # PERSONAL INFORMATION — identity
    page, y = section_heading(doc, page, y, "Personal Information")
    page, y = body_lines(doc, page, y, [
        "Full Name:    Alice Marie Johnson",
        "Date of Birth: 14 March 1991",
        "Nationality:  British",
        "National ID:  NI AB 12 34 56 C",
    ])
    y += 4

    # CONTACT DETAILS — contact_details
    page, y = section_heading(doc, page, y, "Contact Details")
    page, y = body_lines(doc, page, y, [
        "Email:    alice.johnson@securepro.co.uk",
        "Phone:    +44 7911 234567",
        "LinkedIn: linkedin.com/in/alicejohnson-security",
        "Address:  42 Cipher Lane, London, EC1A 1BB, United Kingdom",
    ])
    y += 4

    # PROFESSIONAL EXPERIENCE — employment_history
    page, y = section_heading(doc, page, y, "Professional Experience")

    page, y = body_lines(doc, page, y, [
        "Senior Security Engineer  |  CyberDefense Corp, London  |  Jan 2020 – Present",
    ], bold_first=True)
    page, y = bullet_lines(doc, page, y, [
        "Led a team of 8 engineers to design and deploy a zero-trust network architecture.",
        "Reduced incident response time by 40% by implementing SIEM automation with Splunk.",
        "Conducted red-team exercises for 3 Fortune 500 clients, uncovering 12 critical CVEs.",
        "Architected cloud-native IDS/IPS solution handling 2M events/day on AWS.",
    ])
    y += 6

    page, y = body_lines(doc, page, y, [
        "Security Engineer  |  SecureOps Ltd, Manchester  |  Jun 2016 – Dec 2019",
    ], bold_first=True)
    page, y = bullet_lines(doc, page, y, [
        "Performed penetration testing for 50+ enterprise clients using Burp Suite and Metasploit.",
        "Developed Python-based threat intelligence aggregation scripts.",
        "Designed and delivered internal security awareness training to 300 employees.",
    ])
    y += 6

    page, y = body_lines(doc, page, y, [
        "Junior Security Analyst  |  StartupSec Ltd, Leeds  |  Sep 2014 – May 2016",
    ], bold_first=True)
    page, y = bullet_lines(doc, page, y, [
        "Monitored SOC alerts using IBM QRadar and escalated incidents per runbooks.",
        "Supported vulnerability management programme using Nessus.",
    ])
    y += 4

    # SKILLS — skills_and_tools
    page, y = section_heading(doc, page, y, "Skills & Tools")
    page, y = bullet_lines(doc, page, y, [
        "Languages & Scripting: Python (advanced), Bash, PowerShell, SQL",
        "Security Tools: Splunk, IBM QRadar, Burp Suite, Metasploit, Nessus, Wireshark",
        "Frameworks: MITRE ATT&CK, NIST CSF, ISO 27001, OWASP Top 10",
        "Cloud: AWS Security Hub, Azure Sentinel, Google Chronicle SIEM",
        "Soft Skills: Team leadership, stakeholder communication, risk assessment",
    ])
    y += 4

    # EDUCATION — academic_degrees
    page, y = section_heading(doc, page, y, "Education")
    page, y = body_lines(doc, page, y, [
        "BSc Computer Science (First Class Honours)  |  University College London  |  2011 – 2014",
        "Dissertation: Anomaly Detection in Network Traffic Using Machine Learning",
        "Relevant modules: Cryptography, Network Security, Operating Systems, Algorithms",
    ])
    y += 4

    # CERTIFICATIONS — certifications_training
    page, y = section_heading(doc, page, y, "Certifications & Training")
    page, y = bullet_lines(doc, page, y, [
        "CISSP — Certified Information Systems Security Professional (ISC2, 2018)",
        "CEH — Certified Ethical Hacker (EC-Council, 2017)",
        "AWS Certified Security — Specialty (Amazon, 2021)",
        "SANS SEC504: Hacker Tools, Techniques & Incident Handling (2019)",
    ])
    y += 4

    # COMPENSATION — salary_expectation + current_compensation
    page, y = section_heading(doc, page, y, "Compensation")
    page, y = body_lines(doc, page, y, [
        "Expected Salary:     GBP 95,000 – 110,000 per annum + equity stake",
        "Expected Benefits:   Private health, 30 days annual leave, remote flexibility",
        "Current Salary:      GBP 88,000 base + GBP 8,000 annual performance bonus",
        "Current Package:     Health insurance, pension 8%, 25 days holiday",
    ])
    y += 4

    # REFERENCES — references
    page, y = section_heading(doc, page, y, "Professional References")
    page, y = body_lines(doc, page, y, [
        "Dr Sarah Chen  |  CISO, CyberDefense Corp",
        "Email: s.chen@cyberdefense.co.uk  |  Phone: +44 7700 900123",
        "",
        "Marcus Webb  |  Head of Security, SecureOps Ltd",
        "Email: m.webb@secureops.co.uk  |  Phone: +44 7700 900456",
    ])

    out = OUTPUT_DIR / "Alice_Johnson_Security_Engineer.pdf"
    doc.save(str(out))
    doc.close()
    return out


# ──────────────────────────────────────────────────────────────
# CV 2: Bob Martinez — Junior DevOps Engineer
# ──────────────────────────────────────────────────────────────
def generate_bob() -> Path:
    doc, page, y = new_doc()

    y = header(page, "Bob Martinez", "Junior DevOps Engineer", y)

    # PERSONAL INFORMATION — identity
    page, y = section_heading(doc, page, y, "Personal Information")
    page, y = body_lines(doc, page, y, [
        "Full Name:    Roberto Carlos Martinez",
        "Date of Birth: 22 July 2002",
        "Nationality:  Spanish / British Resident",
    ])
    y += 4

    # CONTACT DETAILS — contact_details
    page, y = section_heading(doc, page, y, "Contact Details")
    page, y = body_lines(doc, page, y, [
        "Email:   bob.martinez.dev@gmail.com",
        "Phone:   +44 7823 456789",
        "GitHub:  github.com/bobmartinez-devops",
        "Address: 7 Pipeline Street, Manchester, M1 2JK",
    ])
    y += 4

    # PROFESSIONAL EXPERIENCE — employment_history
    page, y = section_heading(doc, page, y, "Work Experience")

    page, y = body_lines(doc, page, y, [
        "DevOps Intern  |  CloudBase Inc, Manchester  |  Jun 2024 – Dec 2024 (6 months)",
    ], bold_first=True)
    page, y = bullet_lines(doc, page, y, [
        "Automated CI/CD pipelines with GitHub Actions, reducing build times by 35%.",
        "Containerised 5 legacy microservices using Docker and deployed to Kubernetes (EKS).",
        "Wrote Terraform modules to provision AWS infrastructure (VPC, EC2, RDS, S3).",
        "Assisted in migrating on-premise PostgreSQL database to Amazon RDS with zero downtime.",
        "Wrote Bash scripts for automated log rotation and monitoring alerts.",
    ])
    y += 6

    page, y = body_lines(doc, page, y, [
        "Part-time IT Support  |  University of Manchester IT Services  |  Sep 2022 – May 2024",
    ], bold_first=True)
    page, y = bullet_lines(doc, page, y, [
        "Provided first-line technical support to 1,200+ students and staff.",
        "Configured Linux workstations and resolved network connectivity issues.",
    ])
    y += 4

    # SKILLS — skills_and_tools
    page, y = section_heading(doc, page, y, "Skills & Tools")
    page, y = bullet_lines(doc, page, y, [
        "Containers & Orchestration: Docker, Kubernetes (EKS, kind), Helm",
        "Infrastructure as Code: Terraform, Ansible (basic)",
        "CI/CD: GitHub Actions, Jenkins (basic), GitLab CI",
        "Cloud: AWS (EC2, S3, RDS, IAM, VPC), basic Azure",
        "Languages: Bash, Python (intermediate), YAML, HCL",
        "Monitoring: Prometheus, Grafana, CloudWatch",
        "Operating Systems: Linux (Ubuntu, Amazon Linux), Windows Server",
    ])
    y += 4

    # EDUCATION — academic_degrees
    page, y = section_heading(doc, page, y, "Education")
    page, y = body_lines(doc, page, y, [
        "BSc Software Engineering (2:1)  |  University of Manchester  |  2021 – 2025",
        "GPA: 3.7/4.0  |  Expected graduation: June 2025",
        "Final Year Project: Automated Kubernetes cluster autoscaling with custom metrics",
        "Relevant modules: Cloud Computing, DevOps Practices, Linux Systems, Networking",
    ])
    y += 4

    # CERTIFICATIONS — certifications_training
    page, y = section_heading(doc, page, y, "Certifications & Training")
    page, y = bullet_lines(doc, page, y, [
        "AWS Certified Cloud Practitioner (Amazon, 2024)",
        "HashiCorp Certified: Terraform Associate 003 (HashiCorp, 2024)",
        "Docker Certified Associate — in progress (expected Q3 2025)",
        "Linux Foundation: Introduction to Kubernetes (LFS158, 2023)",
    ])
    y += 4

    # COMPENSATION — salary_expectation (no current salary — first full-time job)
    page, y = section_heading(doc, page, y, "Salary Expectation")
    page, y = body_lines(doc, page, y, [
        "Expected Salary:  GBP 42,000 – 48,000 per annum",
        "Expected Benefits: Learning budget (GBP 2,000/yr), remote-friendly, pension",
        "Availability:     July 2025 (immediately after graduation)",
        "Note: This will be my first full-time position; no current salary to disclose.",
    ])
    y += 4

    # No references section for Bob (testing absence of data)
    page, y = section_heading(doc, page, y, "Additional Information")
    page, y = body_lines(doc, page, y, [
        "Open source contributor to the Helm chart repository (3 merged PRs).",
        "Speaker at University DevOps Society — 'GitOps with ArgoCD' (Feb 2024).",
        "Languages: English (fluent), Spanish (native), French (basic).",
        "References available upon request.",
    ])

    out = OUTPUT_DIR / "Bob_Martinez_Junior_DevOps.pdf"
    doc.save(str(out))
    doc.close()
    return out


# ──────────────────────────────────────────────────────────────
# CV 3: Clara Wei — VP of Engineering
# ──────────────────────────────────────────────────────────────
def generate_clara() -> Path:
    doc, page, y = new_doc()

    y = header(page, "Clara Wei", "VP of Engineering", y)

    # PERSONAL INFORMATION — identity
    page, y = section_heading(doc, page, y, "Personal Information")
    page, y = body_lines(doc, page, y, [
        "Full Name:    Clara Mei-Lin Wei",
        "Date of Birth: 5 September 1980",
        "Nationality:  British-Chinese",
        "Passport:     British (expires 2030)",
    ])
    y += 4

    # CONTACT DETAILS — contact_details
    page, y = section_heading(doc, page, y, "Contact Details")
    page, y = body_lines(doc, page, y, [
        "Email:    clara.wei@executivelevel.io",
        "Phone:    +44 7912 999888",
        "LinkedIn: linkedin.com/in/clarawei-vp",
        "Location: Cambridge, CB2 1TN, United Kingdom",
    ])
    y += 4

    # PROFESSIONAL EXPERIENCE — employment_history
    page, y = section_heading(doc, page, y, "Executive Career History")

    page, y = body_lines(doc, page, y, [
        "VP of Engineering  |  TechGiant plc, London  |  Mar 2019 – Present",
    ], bold_first=True)
    page, y = bullet_lines(doc, page, y, [
        "Oversee 4 engineering departments with 120 engineers across 3 countries.",
        "Delivered 3 major platform re-architectures from monolith to microservices.",
        "Reduced cloud infrastructure costs by GBP 2.4M annually through optimisation.",
        "Established engineering excellence programme: 92% test coverage, 0 critical P1 incidents in 2023.",
        "Led acquisition technical due diligence for 2 AI startups (combined value GBP 45M).",
    ])
    y += 6

    page, y = body_lines(doc, page, y, [
        "Director of Engineering  |  ScaleUp Technologies, Edinburgh  |  Aug 2013 – Feb 2019",
    ], bold_first=True)
    page, y = bullet_lines(doc, page, y, [
        "Grew engineering team from 12 to 65 engineers; introduced agile squads model.",
        "Architected real-time data pipeline processing 500M events/day (Kafka, Spark, Cassandra).",
        "Launched 4 B2B SaaS products serving 200+ enterprise customers across Europe.",
    ])
    y += 6

    page, y = body_lines(doc, page, y, [
        "Senior Software Architect  |  FinTech Dynamics, London  |  Jan 2008 – Jul 2013",
    ], bold_first=True)
    page, y = bullet_lines(doc, page, y, [
        "Designed core payments platform processing GBP 1.2B transactions per month.",
        "Introduced domain-driven design and hexagonal architecture across 8 product teams.",
        "Mentored 20 engineers; ran internal 'Architecture Guild' fortnightly sessions.",
    ])
    y += 6

    page, y = body_lines(doc, page, y, [
        "Software Engineer  |  Innovate Systems, Edinburgh  |  Jul 2003 – Dec 2007",
    ], bold_first=True)
    page, y = bullet_lines(doc, page, y, [
        "Developed Java EE enterprise applications for banking sector clients.",
        "Led migration from Oracle 9i to PostgreSQL, saving GBP 350k/year in licensing.",
    ])
    y += 4

    # SKILLS — skills_and_tools
    page, y = section_heading(doc, page, y, "Skills & Expertise")
    page, y = bullet_lines(doc, page, y, [
        "Leadership: Engineering management, OKR frameworks, hiring at scale, board reporting",
        "Architecture: Microservices, event-driven systems, DDD, cloud-native, API design",
        "Languages: Python (proficient), Java (advanced), Go (familiar), SQL",
        "Cloud & Infra: GCP, AWS, Kubernetes, Terraform, Istio service mesh",
        "Data: Apache Kafka, Spark, dbt, BigQuery, Cassandra",
        "Agile: SAFe, Scrum, Kanban; Jira, Confluence, Linear",
        "Soft Skills: Executive stakeholder management, P&L ownership, M&A due diligence",
    ])
    y += 4

    # EDUCATION — academic_degrees
    page, y = section_heading(doc, page, y, "Education")
    page, y = body_lines(doc, page, y, [
        "MBA (Distinction)  |  London Business School  |  2006 – 2008",
        "Specialisation: Technology Strategy & Innovation, Corporate Finance",
        "Thesis: Platform Ecosystems and Network Effects in B2B SaaS Markets",
        "",
        "BSc Computer Science (First Class Honours)  |  University of Edinburgh  |  1999 – 2003",
        "GPA: 4.0/4.0  |  Class Valedictorian",
        "Dissertation: Distributed Consensus Algorithms for High-Availability Systems",
    ])
    y += 4

    # CERTIFICATIONS — certifications_training
    page, y = section_heading(doc, page, y, "Certifications & Professional Development")
    page, y = bullet_lines(doc, page, y, [
        "PMP — Project Management Professional (PMI, 2010, renewed 2022)",
        "Google Cloud Professional Cloud Architect (Google, 2021)",
        "Scaled Agile Framework (SAFe 5.0 Program Consultant, 2019)",
        "MIT Sloan Executive Education: Leading Organizations & Change (2017)",
        "Stanford Online: Machine Learning Fundamentals (2023)",
    ])
    y += 4

    # COMPENSATION — salary_expectation + current_compensation
    page, y = section_heading(doc, page, y, "Compensation & Expectations")
    page, y = body_lines(doc, page, y, [
        "Expected Package:    GBP 180,000 – 210,000 base salary",
        "Expected Bonus:      20% performance bonus target",
        "Equity:              RSU/ESOP equivalent to 0.5%–1.0% of company over 4 years",
        "Other:               Executive health cover, pension 10%, 35 days annual leave",
        "",
        "Current Base Salary: GBP 165,000 per annum",
        "Current Bonus:       GBP 29,700 (18% of base, paid Q1 2025)",
        "Current Benefits:    BUPA private health, pension 8%, company car allowance GBP 6k/yr",
        "Reason for Leaving:  Seeking a Chief-level role with greater strategic ownership.",
    ])
    y += 4

    # REFERENCES — references
    page, y = section_heading(doc, page, y, "References")
    page, y = body_lines(doc, page, y, [
        "James Okafor  |  CEO, TechGiant plc",
        "Email: j.okafor@techgiant.co.uk  |  Phone: +44 7900 111222",
        "(Available after first interview stage)",
        "",
        "Dr Priya Sharma  |  Independent Board Advisor & ex-CTO, FinTech Dynamics",
        "Email: priya@sharmaadvisory.com  |  Phone: +44 7900 333444",
    ])

    out = OUTPUT_DIR / "Clara_Wei_VP_Engineering.pdf"
    doc.save(str(out))
    doc.close()
    return out


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    generators = [
        ("Alice Johnson — Senior Security Engineer", generate_alice),
        ("Bob Martinez — Junior DevOps Engineer", generate_bob),
        ("Clara Wei — VP of Engineering", generate_clara),
    ]

    for label, fn in generators:
        path = fn()
        print(f"Generated: {path}")

    print("\nAll 3 CVs created in:", OUTPUT_DIR)
    print("\nVerification (pdfplumber read):")
    import pdfplumber
    for pdf_path in sorted(OUTPUT_DIR.glob("*.pdf")):
        with pdfplumber.open(str(pdf_path)) as pdf:
            text = " ".join(p.extract_text() or "" for p in pdf.pages)
        print(f"  {pdf_path.name}: {len(text):,} chars extracted")
