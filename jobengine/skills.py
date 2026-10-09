"""Skill vocabulary used to (a) pull skills out of a resume and (b) find skill gaps in a job."""
from .textutil import has_term

VOCAB = {
    "python": [], "fastapi": [], "flask": [], "django": [],
    "aws": ["amazon web services"], "azure": [], "gcp": ["google cloud"],
    "docker": [], "kubernetes": ["k8s"], "terraform": [], "ansible": [], "jenkins": [],
    "ci/cd": ["cicd", "ci cd", "continuous integration"], "github actions": [], "git": [],
    "linux": [], "bash": ["shell scripting", "shell script"],
    "prometheus": [], "grafana": [], "monitoring": [],
    "sql": [], "postgresql": ["postgres"], "mysql": [], "mongodb": [], "redis": [],
    "rag": ["retrieval augmented generation", "retrieval-augmented generation"],
    "llm": ["llms", "large language model", "large language models"],
    "genai": ["generative ai", "gen ai"], "langchain": [], "crewai": [],
    "pytorch": [], "tensorflow": [], "scikit-learn": ["sklearn", "scikit learn"],
    "machine learning": ["ml"], "deep learning": [], "nlp": ["natural language processing"],
    "pandas": [], "numpy": [], "spark": ["pyspark"], "airflow": [], "kafka": [],
    "rest api": ["rest apis", "restful"], "microservices": ["microservice"],
    "devops": [], "mlops": [], "cloud": [],
    "javascript": [], "typescript": [], "react": [], "java": [],
    "technical support": [], "application support": [], "it support": [], "desktop support": [],
}
_ALIAS = {v: c for c, vs in VOCAB.items() for v in vs}


def canon(term: str) -> str:
    t = (term or "").strip().lower()
    return _ALIAS.get(t, t)


def extract_skills(text: str) -> list:
    t = (text or "").lower()
    return [c for c, vs in VOCAB.items() if has_term(t, c) or any(has_term(t, v) for v in vs)]
