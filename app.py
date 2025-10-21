from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import re
import PyPDF2
import docx
from sentence_transformers import SentenceTransformer, util
import requests
import json
import csv
import time
import pymysql

app = Flask(__name__)
app.secret_key = 'final-csv-version-secret-key'
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
ALLOWED_EXTENSIONS = {'pdf', 'docx'}

# --- Database Connection ---
# Make sure your database credentials are correct
db = pymysql.connect(
    host="localhost",
    user="root",
    password="Ashish@0760", # Replace with your MySQL password if different
    database="resume"
)
cursor = db.cursor()

# --- Helper Functions and Data Loading ---

def load_job_data_from_csv(filepath='job_skills_courses.csv'):
    job_data = {}
    try:
        with open(filepath, mode='r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                category = row['Category']
                skill = row['Skill']
                link = row['Course_Link']
                if category not in job_data:
                    job_data[category] = {}
                job_data[category][skill] = link
        return job_data
    except FileNotFoundError:
        print(f"File '{filepath}' not found.")
        return {}

JOB_DATA = load_job_data_from_csv()
similarity_model = SentenceTransformer('all-MiniLM-L6-v2')
API_CACHE = {}
CACHE_DURATION = 3600

def fetch_jobs_from_api(job_title):
    if job_title in API_CACHE and (time.time() - API_CACHE[job_title]['timestamp']) < CACHE_DURATION:
        return API_CACHE[job_title]['data']
    url = "https://jsearch.p.rapidapi.com/search"
    params = {"query": job_title, "country": "IN", "num_pages": "1"}
    headers = {
        "X-RapidAPI-Key": "71898d73a7mshbf08aa7390a36bcp19a2a1jsn0702957fdcfd", 
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
    }
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        jobs_data = response.json().get('data', [])
        formatted_jobs = []
        for job in jobs_data:
            formatted_jobs.append({
                "title": job.get("job_title"),
                "company": job.get("employer_name"),
                "description": job.get("job_description"),
                "link": job.get("job_apply_link")
            })
        API_CACHE[job_title] = {'timestamp': time.time(), 'data': formatted_jobs[:5]}
        return formatted_jobs[:5]
    except requests.exceptions.RequestException as e:
        print(f"API request failed: {e}")
        return []

def analyze_resume_feedback(resume_text, skill_match_score, skill_gaps):
    strong_points = []
    weak_points = []
    if re.search(r'[\w\.-]+@[\w\.-]+', resume_text) and re.search(r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}', resume_text):
        strong_points.append("✅ Clear Contact Info: Your email and phone number are easy to find.")
    if "experience" in resume_text and "education" in resume_text and "skills" in resume_text:
        strong_points.append("✅ Well-Structured: Includes essential sections.")
    if any(v in resume_text for v in ['managed', 'led', 'developed', 'created']):
        strong_points.append("✅ Uses action verbs effectively.")
    if re.search(r'\b\d+[%]?\b', resume_text):
        strong_points.append("✅ Includes quantifiable results.")
    if skill_match_score > 70:
        strong_points.append(f"✅ High Skill Relevance: {skill_match_score}% match.")
    if not re.search(r'[\w\.-]+@[\w\.-]+', resume_text):
        weak_points.append("⚠️ Missing Contact Info.")
    if len(resume_text.split()) < 250:
        weak_points.append("⚠️ Too short: add more detail.")
    elif len(resume_text.split()) > 1200:
        weak_points.append("⚠️ Too long: shorten your resume.")
    if len(skill_gaps) > 5:
        weak_points.append(f"⚠️ Missing skills like {', '.join(skill_gaps[:3])}.")
    if not weak_points:
        weak_points.append("👍 Resume is strong overall.")
    return {'strong_points': strong_points, 'weak_points': weak_points}

def perform_hybrid_analysis(resume_text, job_category):
    analysis_results = {}
    skills_for_category = JOB_DATA.get(job_category, {})
    master_skills_list = set(skills_for_category.keys())
    recommended_jobs = fetch_jobs_from_api(job_category)
    if recommended_jobs and resume_text:
        resume_embedding = similarity_model.encode(resume_text, convert_to_tensor=True)
        job_descriptions = [job.get('description', '') for job in recommended_jobs]
        job_embeddings = similarity_model.encode(job_descriptions, convert_to_tensor=True)
        cosine_scores = util.cos_sim(resume_embedding, job_embeddings)
        for i, job in enumerate(recommended_jobs):
            job['match_score'] = round(cosine_scores[0][i].item() * 100, 2)
        recommended_jobs.sort(key=lambda x: x.get('match_score', 0), reverse=True)
    analysis_results['recommended_jobs'] = recommended_jobs
    detected_skills = [skill for skill in master_skills_list if skill.lower() in resume_text]
    skill_gaps = list(master_skills_list - set(detected_skills))
    analysis_results['detected_skills'] = detected_skills
    analysis_results['skill_gaps'] = skill_gaps
    grouped_courses = {}
    for skill in skill_gaps:
        course_link = skills_for_category.get(skill)
        if course_link:
            grouped_courses[skill] = [{"name": f"Course for {skill}", "link": course_link}]
    analysis_results['suggested_courses'] = grouped_courses
    ats_score = 50
    if re.search(r'@', resume_text): ats_score += 15
    if "experience" in resume_text: ats_score += 15
    if "education" in resume_text: ats_score += 20
    analysis_results['ats_compatibility'] = min(ats_score, 100)
    total_skills = len(master_skills_list)
    skill_match_score = int((len(detected_skills) / total_skills) * 100) if total_skills else 0
    top_match_score = recommended_jobs[0]['match_score'] if recommended_jobs else 0
    analysis_results['overall_score'] = int((top_match_score + skill_match_score + analysis_results['ats_compatibility']) / 3)
    analysis_results['skill_match_score'] = skill_match_score
    feedback = analyze_resume_feedback(resume_text, skill_match_score, skill_gaps)
    analysis_results['strong_points'] = feedback['strong_points']
    analysis_results['weak_points'] = feedback['weak_points']
    return analysis_results

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_likely_resume(text):
    score = sum(bool(re.search(p, text, re.IGNORECASE)) for p in ['email', 'experience', 'education', 'skills', 'objective', 'summary'])
    return score >= 2

def parse_resume(file_path):
    text = ""
    try:
        if file_path.lower().endswith(".pdf"):
            with open(file_path, "rb") as file:
                reader = PyPDF2.PdfReader(file)
                for page in reader.pages:
                    text += page.extract_text() or ""
        elif file_path.lower().endswith(".docx"):
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                text += para.text + "\n"
    except Exception as e:
        print(f"Error parsing file {file_path}: {e}")
        return ""
    return text.lower()

# --- Flask Routes ---

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        fullname = request.form['fullname']
        email = request.form['email']
        password = request.form['password']
        interest = request.form['interest']
        if len(password) < 8 or not re.search(r'[@$!%*?&]', password):
            flash('Password must be at least 8 characters and include a special symbol.', 'error')
            return redirect(url_for('register'))
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        if cursor.fetchone():
            flash('An account with this email already exists.', 'error')
            return redirect(url_for('register'))
        hashed_password = generate_password_hash(password)
        try:
            cursor.execute("INSERT INTO users (fullname, email, password, interest) VALUES (%s, %s, %s, %s)",
                           (fullname, email, hashed_password, interest))
            db.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        except:
            db.rollback()
            flash('An error occurred during registration. Please try again.', 'error')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        cursor.execute("SELECT fullname, email, password, interest FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()
        if user and check_password_hash(user[2], password):
            session['user'] = {'fullname': user[0], 'email': user[1], 'interest': user[3]}
            flash('Login successful.', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid email or password. Please try again.', 'error')
    return render_template('login.html')

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    user = session['user']
    fullname = user['fullname']
    interest = user['interest']

    cursor.execute("SELECT id, filename FROM resumes WHERE user_email = %s ORDER BY upload_date DESC", (user['email'],))
    uploaded_resumes = cursor.fetchall()

    if request.method == 'POST':
        if 'resume' not in request.files or request.files['resume'].filename == '':
            flash('No file selected.', 'error')
            return redirect(request.url)

        file = request.files['resume']
        if not allowed_file(file.filename):
            flash('Invalid file type. Please upload a PDF or DOCX file.', 'error')
            return redirect(request.url)
        
        filename = secure_filename(file.filename)
        
        ## ADDED: Check if a resume with the same name already exists for this user
        try:
            cursor.execute("SELECT id FROM resumes WHERE user_email = %s AND filename = %s", (user['email'], filename))
            existing_resume = cursor.fetchone()
            if existing_resume:
                flash(f"A resume named '{filename}' already exists. Please upload a new file with a different name.", 'error')
                return redirect(url_for('dashboard'))
        except Exception as e:
            db.rollback()
            flash(f"Database error when checking for existing resume: {e}", 'error')
            return redirect(url_for('dashboard'))

        user_folder = secure_filename(fullname)
        user_dir = os.path.join(app.config['UPLOAD_FOLDER'], user_folder)
        os.makedirs(user_dir, exist_ok=True)
        file_path = os.path.join(user_dir, filename)
        file.save(file_path)

        try:
            cursor.execute("INSERT INTO resumes (user_email, filename, filepath) VALUES (%s, %s, %s)",
                           (user['email'], filename, file_path))
            db.commit()
        except Exception as e:
            db.rollback()
            flash(f'Error saving resume record to database: {e}', 'error')
            return redirect(request.url)

        resume_text = parse_resume(file_path)
        if not resume_text.strip():
            flash('The uploaded file is empty or could not be read.', 'error')
            return render_template('dashboard.html', fullname=fullname, interest=interest, uploaded_resumes=uploaded_resumes)
        
        if not is_likely_resume(resume_text):
            flash('The content of the file does not appear to be a valid resume.', 'error')
            return render_template('dashboard.html', fullname=fullname, interest=interest, uploaded_resumes=uploaded_resumes)
        
        analysis = perform_hybrid_analysis(resume_text, interest)
        
        cursor.execute("SELECT id, filename FROM resumes WHERE user_email = %s ORDER BY upload_date DESC", (user['email'],))
        updated_resumes = cursor.fetchall()
        return render_template('dashboard.html', fullname=fullname, interest=interest, analysis=analysis, uploaded_resumes=updated_resumes)
    
    return render_template('dashboard.html', fullname=fullname, interest=interest, uploaded_resumes=uploaded_resumes)


@app.route('/analyze/<int:resume_id>')
def analyze_resume(resume_id):
    if 'user' not in session:
        return redirect(url_for('login'))

    user = session['user']
    
    cursor.execute("SELECT filepath FROM resumes WHERE id = %s AND user_email = %s", (resume_id, user['email']))
    resume_record = cursor.fetchone()

    if not resume_record:
        flash('Resume not found or you do not have permission to view it.', 'error')
        return redirect(url_for('dashboard'))

    file_path = resume_record[0]
    resume_text = parse_resume(file_path)
    
    if not resume_text.strip():
        flash('Could not read the selected resume file. It might be corrupted or empty.', 'error')
        return redirect(url_for('dashboard'))

    cursor.execute("SELECT id, filename FROM resumes WHERE user_email = %s ORDER BY upload_date DESC", (user['email'],))
    uploaded_resumes = cursor.fetchall()

    analysis = perform_hybrid_analysis(resume_text, user['interest'])
    return render_template('dashboard.html', fullname=user['fullname'], interest=user['interest'], analysis=analysis, uploaded_resumes=uploaded_resumes)


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)

