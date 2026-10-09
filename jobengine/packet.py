"""Per-job application packet: resume lines worth highlighting + a cover-letter draft. No LLM, no invented claims."""
from .skills import canon, extract_skills


def build_packet(profile: dict, job: dict) -> dict:
    resume = profile.get("resume_text") or ""
    job_text = f"{job.get('title', '')} {job.get('description') or ''}"
    job_skills = set(extract_skills(job_text))
    mine = {canon(s) for s in (profile.get("skills") or "").split(",") if s.strip()} | set(extract_skills(resume))
    matched = [s for s in extract_skills(job_text) if s in mine][:6]
    gaps = [s for s in extract_skills(job_text) if s not in mine][:6]

    lines = [l.strip(" -\u2022*\t") for l in resume.splitlines() if len(l.strip()) > 25]
    ranked = sorted(((len(set(extract_skills(l)) & job_skills), l) for l in lines), key=lambda x: -x[0])
    bullets = [l for n, l in ranked if n > 0][:5]

    name = profile.get("full_name") or "[Your name]"
    skills_txt = ", ".join(matched[:4]) if matched else "[skills relevant to this role]"
    notice = f" My notice period is {profile['notice_period']}." if profile.get("notice_period") else ""
    title = (job.get("title") or "").lower()
    if "support" in title or "intern" in title:
        project_sentence = (
            "During my internship at Besant Technologies, I built Jenkins pipelines for Dockerized apps and "
            "administered Linux servers; I am also keen to grow my IT support and endpoint operations skills."
        )
    else:
        project_sentence = (
            "In my completed Meeting Intelligence Bot project, I used Jenkins and Docker for CI/CD, "
            "provisioned AWS infrastructure with Terraform, deployed to k3s, and added Prometheus and Grafana monitoring."
        )
    letter = (
        f"Dear Hiring Team at {job.get('company', '[Company]')},\n\n"
        f"I am applying for the {job.get('title', '[Role]')} position. My background includes hands-on work with "
        f"{skills_txt}. {project_sentence}\n\n"
        f"I would welcome the chance to discuss how I can contribute to your team.{notice}\n\n"
        f"Thank you for your time,\n{name}"
    )
    return {"matched_skills": matched, "skills_to_learn": gaps, "resume_bullets": bullets, "cover_letter": letter}
