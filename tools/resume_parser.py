import os

def get_resume_text() -> str:
    resume_path = os.path.join(os.path.dirname(__file__), "..", "CV.txt")
    if not os.path.exists(resume_path):
        return ""
    
    try:
        with open(resume_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"Error reading resume: {e}")
        return ""
