from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from supabase import create_client, Client
import re
from datetime import datetime, timedelta, timezone
import google.generativeai as genai
import os
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", 'your-super-secret-key-change-this-in-production')

# Configure Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

# Configure Supabase
try:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    
    if not supabase_url or not supabase_key:
        raise Exception("Missing SUPABASE_URL or SUPABASE_KEY in environment")
    
    supabase: Client = create_client(supabase_url, supabase_key)
    print("✅ Connected to Supabase successfully!")
    
    # Test connection (optional - can be removed for production)
    try:
        test_response = supabase.table('users').select('id').limit(1).execute()
        print("✅ Database tables verified and accessible!")
    except:
        print("⚠️ Database test query failed, but connection established")
    
except Exception as e:
    print(f"❌ Supabase connection error: {e}")
    supabase = None

# Configure upload settings for Vercel (use /tmp for serverless)
UPLOAD_FOLDER = '/tmp/uploads' if os.environ.get('VERCEL') else 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Create upload directories
try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(os.path.join(UPLOAD_FOLDER, 'certificates'), exist_ok=True)
    os.makedirs(os.path.join(UPLOAD_FOLDER, 'additional'), exist_ok=True)
except Exception as e:
    print(f"Upload folder creation warning: {e}")

# PM Internship Scheme Knowledge Base
INTERNSHIP_CONTEXT = """
You are an AI assistant for the PM Internship Scheme, a Government of India initiative. Here's key information:

ELIGIBILITY CRITERIA:
- Age: 21-24 years
- Indian citizen with valid documents
- Not enrolled in full-time education during internship
- Not in full-time employment
- Family income less than ₹8 lakhs per annum
- No family member should have a government job

BENEFITS:
- Monthly stipend: ₹5,000 (₹4,500 from government + ₹500 from company)
- One-time grant: ₹6,000 for learning materials
- Health and accident insurance coverage
- Official internship certificate upon completion
- Industry exposure and mentorship

APPLICATION PROCESS:
1. Check eligibility criteria
2. Register on the official portal
3. Fill the application form completely
4. Upload required documents (Aadhaar, educational certificates, income certificate, bank details, photo)
5. Submit application
6. Track status in 'My Applications' section

DURATION: Typically 12 months, may vary by sector/company

SECTORS: IT & Technology, Healthcare, Finance & Banking, Manufacturing, Government Organizations

CONTACT SUPPORT:
- Email: [contact-pminternship@gov.in](mailto:contact-pminternship@gov.in)
- Phone: 011-12345678 (10 AM - 6 PM, Monday-Friday)

Always be helpful, accurate, and professional. Keep responses concise but comprehensive. Use emojis appropriately.
"""

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def check_email_exists(email):
    """Check if email already exists using Supabase"""
    try:
        if not supabase:
            return False
        response = supabase.table('users').select('email').eq('email', email.strip().lower()).execute()
        return len(response.data) > 0
    except Exception as e:
        print(f"Error checking email: {e}")
        return False

def create_user(full_name, email, password):
    """Create a new user in Supabase"""
    try:
        if not supabase:
            return False, "Database connection not available"
            
        if check_email_exists(email):
            return False, "Email already registered"
        
        password_hash = generate_password_hash(password)
        
        user_data = {
            "full_name": full_name.strip(),
            "email": email.strip().lower(),
            "password_hash": password_hash
        }
        
        print(f"Creating user: {email}")
        response = supabase.table('users').insert(user_data).execute()
        
        if response.data and len(response.data) > 0:
            print(f"✅ User created successfully: ID {response.data[0]['id']}")
            return True, "User created successfully"
        else:
            print(f"❌ No data returned: {response}")
            return False, "Error creating user - no data returned"
        
    except Exception as e:
        print(f"❌ Error creating user: {e}")
        error_str = str(e).lower()
        if "duplicate" in error_str or "unique" in error_str:
            return False, "Email already registered"
        return False, "Error creating account. Please try again."

def verify_user(email, password):
    """Verify user credentials using Supabase"""
    try:
        if not supabase:
            return None
        response = supabase.table('users').select('*').eq('email', email.strip().lower()).execute()
        
        if response.data:
            user = response.data[0]
            if check_password_hash(user['password_hash'], password):
                return user
        return None
    except Exception as e:
        print(f"Error verifying user: {e}")
        return None

def update_last_login(user_id):
    """Update user's last login timestamp"""
    try:
        if not supabase:
            return
        supabase.table('users').update({
            "last_login": datetime.now(timezone.utc).isoformat()
        }).eq('id', user_id).execute()
    except Exception as e:
        print(f"Error updating last login: {e}")

def get_user_by_id(user_id):
    """Get user by ID from Supabase"""
    try:
        if not supabase:
            return None
        response = supabase.table('users').select('*').eq('id', user_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error getting user by ID: {e}")
        return None

def update_user_profile(user_id, profile_data):
    """Update user profile in Supabase"""
    try:
        if not supabase:
            return False
        clean_data = {}
        for key, value in profile_data.items():
            if value is not None and value != '':
                clean_data[key] = value
        
        response = supabase.table('users').update(clean_data).eq('id', user_id).execute()
        return len(response.data) > 0
    except Exception as e:
        print(f"Error updating user profile: {e}")
        return False

def log_conversation(user_message, bot_response, user_id=None):
    """Log conversations using Supabase"""
    try:
        if not supabase:
            return
        chat_data = {
            "user_id": user_id,
            "user_message": user_message,
            "bot_response": bot_response
        }
        supabase.table('chat_logs').insert(chat_data).execute()
    except Exception as e:
        print(f"Logging error: {e}")

def validate_password(password):
    """Validate password strength"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain an uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain a lowercase letter"
    if not re.search(r'\d', password):
        return False, "Password must contain a number"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain a special character"
    return True, "Password is valid"

def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def get_user_initials(full_name):
    """Get user initials from full name"""
    if not full_name or full_name == 'User':
        return "U"
    names = full_name.strip().split()
    if len(names) >= 2:
        return (names[0][0] + names[-1][0]).upper()
    else:
        return names[0][0].upper()

def get_user_display_name(full_name, email):
    """Get display name from full name or email"""
    if full_name and full_name != 'User':
        return full_name
    else:
        return email.split('@')[0].title()

def get_gemini_response(user_message, user_name="User", user_email=""):
    """Get response from Google Gemini with PM Internship context"""
    try:
        full_prompt = f"""
        {INTERNSHIP_CONTEXT}
        
        The user's name is {user_name} and their email is {user_email}. 
        Address them personally when appropriate.
        
        User question: {user_message}
        
        Provide a helpful response about the PM Internship Scheme:
        """
        
        response = model.generate_content(
            full_prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=400,
                temperature=0.7,
            )
        )
        
        return response.text.strip()
        
    except Exception as e:
        print(f"Gemini API error: {e}")
        return get_fallback_response(user_message)

def get_fallback_response(message):
    """Enhanced fallback responses"""
    message_lower = message.lower()
    
    if any(word in message_lower for word in ['hi', 'hello', 'hey', 'namaste']):
        return "👋 Hello! I'm your PM Internship Assistant. How can I help you today?"
    elif any(word in message_lower for word in ['apply', 'application', 'how to']):
        return "🎯 **Application Process:**\n1️⃣ Check eligibility criteria\n2️⃣ Register on portal\n3️⃣ Fill application form\n4️⃣ Upload documents\n5️⃣ Submit application\n\n📱 Visit the Apply section for detailed steps!"
    elif any(word in message_lower for word in ['eligible', 'eligibility', 'criteria']):
        return "✅ **Eligibility Checklist:**\n🔹 Age: 21-24 years\n🔹 Indian citizen\n🔹 Not in full-time work/education\n🔹 Family income < ₹8 lakhs\n🔹 No govt job in family"
    elif any(word in message_lower for word in ['stipend', 'benefit', 'salary', 'money']):
        return "💰 **Amazing Benefits:**\n💵 ₹5,000 monthly stipend\n🎁 ₹6,000 one-time grant\n🏥 Health insurance\n📜 Official certificate\n🌟 Industry mentorship"
    elif any(word in message_lower for word in ['help', 'support', 'contact']):
        return "📞 **Need Help?**\n📧 Email: contact-pminternship@gov.in\n☎️ Phone: 011-12345678\n🕒 Mon-Fri: 10 AM - 6 PM"
    else:
        return "🤖 I can help you with:\n🔹 Eligibility criteria\n🔹 Application process\n🔹 Benefits & stipend\n🔹 Required documents\n🔹 Contact support\n\nWhat would you like to know?"

def generate_recommendations_fast(user):
    """Fast AI recommendations with timeout"""
    try:
        # Shorter, more focused prompt for faster response
        prompt = f"""
        Generate 6 internship recommendations for:
        - Skills: {user.get('skills', 'General')}
        - Interest: {user.get('area_of_interest', 'IT')}
        - Education: {user.get('qualification', 'Graduate')}
        
        JSON format: [{{"company":"Name","title":"Position","type":"government|service-based","sector":"Sector","skills":["skill1","skill2"],"duration":"X Months","location":"City","stipend":"₹X/month","description":"Brief desc"}}]
        """
        
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=800,  # Reduced tokens for faster response
                temperature=0.7,
            )
        )
        
        recommendations_text = response.text.strip()
        start_idx = recommendations_text.find('[')
        end_idx = recommendations_text.rfind(']') + 1
        
        if start_idx != -1 and end_idx != -1:
            json_str = recommendations_text[start_idx:end_idx]
            recommendations = json.loads(json_str)
            return recommendations[:6]
        else:
            raise Exception("Could not parse AI response")
            
    except Exception as e:
        print(f"Fast AI recommendation error: {e}")
        return get_enhanced_default_recommendations(user)

def get_enhanced_default_recommendations(user):
    """Enhanced default recommendations based on user profile"""
    area_of_interest = user.get('area_of_interest', '').lower()
    skills = user.get('skills', '').lower()
    qualification = user.get('qualification', '').lower()
    user_name = user.get('full_name', 'you')
    
    # Personalized IT recommendations
    if 'information technology' in area_of_interest or 'software' in area_of_interest:
        return [
            {
                "company": "TCS (Tata Consultancy Services)",
                "title": "Software Development Intern",
                "type": "service-based",
                "sector": "IT Services",
                "skills": ["Java", "Python", "Problem Solving", "Communication"],
                "duration": "3 Months",
                "location": "Multiple Cities",
                "stipend": "₹30,000/month",
                "description": f"Perfect for {user_name} with {qualification} background. Work on enterprise software projects and gain real-world coding experience."
            },
            {
                "company": "ISRO",
                "title": "Technology Intern",
                "type": "government",
                "sector": "Space Technology",
                "skills": ["Programming", "Research", "Data Analysis", "Innovation"],
                "duration": "6 Months",
                "location": "Bangalore",
                "stipend": "₹25,000/month",
                "description": "Contribute to India's space missions. Excellent match for your technical skills and scientific interests."
            },
            {
                "company": "Infosys",
                "title": "Digital Innovation Intern",
                "type": "service-based",
                "sector": "IT Consulting",
                "skills": ["Digital Literacy", "Innovation", "Teamwork", "Problem Solving"],
                "duration": "3 Months",
                "location": "Pune/Bangalore",
                "stipend": "₹28,000/month",
                "description": "Work on cutting-edge digital transformation projects. Perfect stepping stone for your IT career."
            },
            {
                "company": "DRDO",
                "title": "Research Intern",
                "type": "government",
                "sector": "Defence Research",
                "skills": ["Research", "Technical Analysis", "Problem Solving", "Documentation"],
                "duration": "4 Months",
                "location": "Delhi/Hyderabad",
                "stipend": "₹20,000/month",
                "description": "Join national defence research projects. Build technical expertise in cutting-edge technologies."
            },
            {
                "company": "Wipro",
                "title": "Cloud Technology Intern",
                "type": "service-based",
                "sector": "Cloud Services",
                "skills": ["Cloud Computing", "AWS", "Problem Solving", "Learning Agility"],
                "duration": "4 Months",
                "location": "Pune",
                "stipend": "₹32,000/month",
                "description": "Gain hands-on cloud experience with enterprise clients. High-demand skills for your future."
            },
            {
                "company": "HCL Technologies",
                "title": "Technology Trainee",
                "type": "service-based",
                "sector": "IT Services",
                "skills": ["Programming", "Database", "Web Technologies", "Communication"],
                "duration": "3 Months",
                "location": "Noida/Chennai",
                "stipend": "₹26,000/month",
                "description": "Comprehensive technology training program. Build industry-ready skills with mentorship support."
            }
        ]
    
    # AI/ML specialized recommendations
    elif 'artificial intelligence' in area_of_interest or 'machine learning' in area_of_interest:
        return [
            {
                "company": "Google India",
                "title": "AI/ML Research Intern",
                "type": "service-based",
                "sector": "Artificial Intelligence",
                "skills": ["Python", "Machine Learning", "TensorFlow", "Data Science"],
                "duration": "4 Months",
                "location": "Bangalore",
                "stipend": "₹45,000/month",
                "description": f"Perfect for {user_name}! Work on cutting-edge AI research with Google's world-class team."
            },
            {
                "company": "Microsoft India",
                "title": "Data Science Intern",
                "type": "service-based",
                "sector": "Data Science",
                "skills": ["Python", "R", "Statistical Analysis", "Azure ML"],
                "duration": "3 Months",
                "location": "Hyderabad",
                "stipend": "₹40,000/month",
                "description": "Analyze big data and build ML models. Excellent opportunity to work with Microsoft's AI platform."
            },
            {
                "company": "ISRO",
                "title": "Data Analytics Intern",
                "type": "government",
                "sector": "Space Data Science",
                "skills": ["Data Analysis", "Python", "Satellite Data", "Research"],
                "duration": "5 Months",
                "location": "Bangalore",
                "stipend": "₹25,000/month",
                "description": "Apply AI/ML to space data analysis. Unique opportunity to work with satellite imagery and space research."
            },
            {
                "company": "TCS Research",
                "title": "AI Innovation Intern",
                "type": "service-based",
                "sector": "AI Research",
                "skills": ["Machine Learning", "Deep Learning", "Python", "Research"],
                "duration": "4 Months",
                "location": "Pune",
                "stipend": "₹35,000/month",
                "description": "Work on breakthrough AI innovations. Contribute to next-generation AI solutions for global clients."
            },
            {
                "company": "IIT Research Labs",
                "title": "AI Research Assistant",
                "type": "government",
                "sector": "Academic Research",
                "skills": ["Research", "Python", "ML Algorithms", "Technical Writing"],
                "duration": "6 Months",
                "location": "Multiple IITs",
                "stipend": "₹20,000/month",
                "description": "Collaborate with top researchers on AI projects. Great for building research experience and academic credentials."
            },
            {
                "company": "Wipro AI Labs",
                "title": "ML Engineering Intern",
                "type": "service-based",
                "sector": "AI Engineering",
                "skills": ["MLOps", "Python", "Cloud Platforms", "Model Deployment"],
                "duration": "3 Months",
                "location": "Bangalore",
                "stipend": "₹32,000/month",
                "description": "Learn ML engineering best practices. Deploy AI models at scale for enterprise applications."
            }
        ]
    
    # General recommendations for other interests
    return [
        {
            "company": "Reliance Industries",
            "title": "Management Trainee",
            "type": "service-based",
            "sector": "Business Management",
            "skills": ["Leadership", "Communication", "Business Analysis", "Project Management"],
            "duration": "6 Months",
            "location": "Mumbai",
            "stipend": "₹35,000/month",
            "description": f"Perfect for {user_name} to develop leadership skills. Comprehensive exposure to business operations."
        },
        {
            "company": "HDFC Bank",
            "title": "Banking Operations Intern",
            "type": "service-based",
            "sector": "Financial Services",
            "skills": ["Financial Analysis", "Customer Service", "Banking Operations", "Communication"],
            "duration": "3 Months",
            "location": "Multiple Cities",
            "stipend": "₹25,000/month",
            "description": "Gain experience in India's leading private bank. Learn banking operations and financial services."
        },
        {
            "company": "NITI Aayog",
            "title": "Policy Research Intern",
            "type": "government",
            "sector": "Public Policy",
            "skills": ["Research", "Policy Analysis", "Report Writing", "Data Interpretation"],
            "duration": "4 Months",
            "location": "New Delhi",
            "stipend": "₹18,000/month",
            "description": "Contribute to national policy making. Research socio-economic issues and policy solutions."
        },
        {
            "company": "Mahindra Group",
            "title": "Business Development Intern",
            "type": "service-based",
            "sector": "Automotive & Business",
            "skills": ["Business Development", "Market Research", "Communication", "Strategic Thinking"],
            "duration": "4 Months",
            "location": "Pune/Mumbai",
            "stipend": "₹28,000/month",
            "description": "Work with India's leading automotive company. Develop business strategy and market analysis skills."
        },
        {
            "company": "Indian Railways",
            "title": "Operations Intern",
            "type": "government",
            "sector": "Transportation",
            "skills": ["Operations Management", "Logistics", "Problem Solving", "Team Coordination"],
            "duration": "5 Months",
            "location": "Multiple Cities",
            "stipend": "₹15,000/month",
            "description": "Learn operations of world's largest railway network. Great exposure to logistics and operations management."
        },
        {
            "company": "Larsen & Toubro",
            "title": "Engineering Trainee",
            "type": "service-based",
            "sector": "Engineering & Construction",
            "skills": ["Engineering Principles", "Project Management", "CAD", "Technical Communication"],
            "duration": "6 Months",
            "location": "Chennai/Mumbai",
            "stipend": "₹24,000/month",
            "description": "Work on large-scale engineering projects. Build practical engineering skills with industry leader."
        }
    ]

def get_default_recommendations(user):
    """Legacy function - calls enhanced version"""
    return get_enhanced_default_recommendations(user)

@app.before_request
def clear_stale_flash_messages():
    """Clear flash messages for non-authenticated users"""
    if request.endpoint not in ['login', 'signup', 'logout', 'clear_session'] and not session.get('logged_in'):
        if '_flashes' in session:
            session.pop('_flashes', None)

# Routes
@app.route('/')
def index():
    return render_template('login.html')

@app.route('/home')
def home():
    if not session.get('logged_in'):
        flash('Please login to access the home page', 'error')
        return redirect(url_for('index'))
    
    user_name = session.get('user_name', 'User')
    user_email = session.get('user_email', '')
    user_initials = session.get('user_initials', 'U')
    
    return render_template('home.html', 
                         user_name=user_name,
                         user_email=user_email, 
                         user_initials=user_initials)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember')
        
        # Clear any existing flash messages
        session.pop('_flashes', None)
        
        # Basic validation
        if not email or not password:
            flash('📝 Please enter both email and password', 'error')
            return render_template('login.html')
        
        # Email format validation
        if not validate_email(email):
            flash('📧 Please enter a valid email address', 'error')
            return render_template('login.html')
        
        # Verify user credentials
        user = verify_user(email, password)
        
        if user:
            # Login successful
            try:
                full_name = user['full_name'] if user['full_name'] and user['full_name'] != 'User' else get_user_display_name(None, user['email'])
            except (KeyError, TypeError):
                full_name = get_user_display_name(None, user['email'])
            
            # Set session data
            session['user_id'] = user['id']
            session['user_name'] = full_name
            session['user_email'] = user['email']
            session['user_initials'] = get_user_initials(full_name)
            session['logged_in'] = True
            
            update_last_login(user['id'])
            
            if remember:
                session.permanent = True
                app.permanent_session_lifetime = timedelta(days=30)
            
            flash(f'🎉 Welcome back, {full_name}!', 'success')
            return redirect(url_for('home'))
        else:
            # Login failed - check specific reason
            if check_email_exists(email):
                flash('❌ Incorrect password. Please check your password and try again.', 'error')
            else:
                flash('❌ No account found with this email address.', 'error')
                flash(f'💡 Don\'t have an account? <a href="{url_for("signup")}" class="alert-link text-decoration-none"><strong>Sign up here</strong></a> to get started!', 'info')
            
            return render_template('login.html')
    
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        session.pop('_flashes', None)
        
        if not full_name or not email or not password or not confirm_password:
            flash('All fields are required', 'error')
            return render_template('signup.html')
        
        if len(full_name.strip()) < 2:
            flash('Full name must be at least 2 characters long', 'error')
            return render_template('signup.html')
        
        if not validate_email(email):
            flash('Please enter a valid email address', 'error')
            return render_template('signup.html')
        
        if check_email_exists(email):
            flash('This email is already registered. Please use a different email or try logging in.', 'error')
            return render_template('signup.html')
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('signup.html')
        
        is_valid, message = validate_password(password)
        if not is_valid:
            flash(message, 'error')
            return render_template('signup.html')
        
        success, message = create_user(full_name, email, password)
        if success:
            # Enhanced success message
            flash(f'🎉 Welcome {full_name}! Your account has been created successfully. Please login to continue.', 'success')
            return redirect(url_for('login'))
        else:
            flash(message, 'error')
            return render_template('signup.html')
    
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully', 'success')
    return redirect(url_for('index'))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if not session.get('logged_in'):
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        try:
            form_data = {
                'full_name': request.form.get('full_name'),
                'father_name': request.form.get('father_name'),
                'gender': request.form.get('gender'),
                'phone': request.form.get('phone'),
                'district': request.form.get('district'),
                'address': request.form.get('address'),
                'qualification': request.form.get('qualification'),
                'qualification_marks': float(request.form.get('qualification_marks')) if request.form.get('qualification_marks') else None,
                'course': request.form.get('course'),
                'course_marks': float(request.form.get('course_marks')) if request.form.get('course_marks') else None,
                'area_of_interest': request.form.get('area_of_interest'),
                'skills': request.form.get('skills'),
                'languages': request.form.get('languages'),
                'experience': request.form.get('experience'),
                'prior_internship': request.form.get('prior_internship'),
                'otp_verified': True,
                'registration_completed': True,
                'profile_completed': True
            }
            
            # Handle file uploads (simplified for Vercel serverless)
            file_paths = {}
            
            # Note: For production on Vercel, consider using cloud storage
            # like Supabase Storage, AWS S3, or Cloudinary for file uploads
            
            if update_user_profile(session.get('user_id'), {**form_data, **file_paths}):
                if form_data['full_name']:
                    session['user_name'] = form_data['full_name']
                    session['user_initials'] = get_user_initials(form_data['full_name'])
                
                session.pop('_flashes', None)
                flash('Profile updated successfully!', 'success')
            else:
                flash('Error updating profile. Please try again.', 'error')
            
            return redirect(url_for('profile'))
            
        except Exception as e:
            print(f"Profile update error: {e}")
            session.pop('_flashes', None)
            flash('Error updating profile. Please try again.', 'error')
            return redirect(url_for('profile'))
    
    user = get_user_by_id(session.get('user_id'))
    
    if not user:
        return redirect(url_for('index'))
    
    return render_template('profile.html', 
                         user=user,
                         user_name=session.get('user_name', 'User'),
                         user_email=session.get('user_email', ''),
                         user_initials=session.get('user_initials', 'U'))

@app.route('/recommendations')
def recommendations():
    if not session.get('logged_in'):
        return redirect(url_for('index'))
    
    user = get_user_by_id(session.get('user_id'))
    if not user:
        return redirect(url_for('index'))
    
    # Check if profile is completed
    if not user.get('profile_completed'):
        flash('Please complete your profile first to get recommendations.', 'warning')
        return redirect(url_for('profile'))
    
    # FAST LOADING: Always start with enhanced default recommendations
    recommendations = get_enhanced_default_recommendations(user)
    
    return render_template('recommendations.html', 
                         user=user,
                         recommendations=recommendations,
                         user_name=session.get('user_name', 'User'),
                         user_email=session.get('user_email', ''),
                         user_initials=session.get('user_initials', 'U'))

@app.route('/api/generate-ai-recommendations')
def generate_ai_recommendations():
    """AJAX endpoint to generate AI recommendations in background"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    user = get_user_by_id(session.get('user_id'))
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    try:
        # Try to generate AI recommendations with timeout
        ai_recommendations = generate_recommendations_fast(user)
        return jsonify({
            'success': True,
            'recommendations': ai_recommendations
        })
    except Exception as e:
        print(f"AI recommendations error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        
        if not user_message:
            return jsonify({'error': 'No message provided'}), 400
        
        user_name = session.get('user_name', 'User')
        user_email = session.get('user_email', '')
        
        bot_response = get_gemini_response(user_message, user_name, user_email)
        log_conversation(user_message, bot_response, session.get('user_id'))
        
        return jsonify({
            'reply': bot_response,
            'success': True
        })
    
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({
            'reply': '⚠️ I apologize, but I encountered an error. Please try again or contact support.',
            'success': False
        }), 500

@app.route('/clear-session')
def clear_session():
    session.clear()
    return redirect(url_for('index'))

@app.route('/debug-users')
def debug_users():
    """Debug route to see all users"""
    if not app.debug:
        return "Not available in production"
    
    try:
        if not supabase:
            return "Database connection not available"
            
        response = supabase.table('users').select('id, full_name, email, created_at').execute()
        users = response.data
        
        output = "<h2>Registered Users (Supabase):</h2><ul>"
        for user in users:
            output += f"<li>ID: {user['id']}, Name: {user['full_name']}, Email: {user['email']}, Created: {user['created_at']}</li>"
        output += "</ul>"
        output += "<br><a href='/clear-session'>Clear Session</a> | <a href='/'>Home</a>"
        
        return output
    except Exception as e:
        return f"Error fetching users: {e}"

# Health check endpoint for Vercel
@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now(timezone.utc).isoformat()})

# Vercel serverless function handler
if __name__ == '__main__':
    print("🚀 Starting PM Internship App with Fast Recommendations...")
    print(f"✅ Supabase URL: {os.getenv('SUPABASE_URL')}")
    app.run(debug=False)  # Set to False for production

# For Vercel deployment
app = app
