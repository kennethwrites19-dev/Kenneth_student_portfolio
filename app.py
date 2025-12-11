import os
import secrets
import json  # <--- NEW: Required for handling lists
from io import BytesIO
from datetime import datetime
from flask import (
    Flask, render_template, redirect, url_for,
    request, flash, send_file
)
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.utils import secure_filename

# PDF Imports
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet

# -----------------------
# App Configuration
# -----------------------
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///portfolio.db'
app.config['SECRET_KEY'] = 'replace_with_your_secret_key'
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2 MB max upload
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Create upload folder
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize extensions
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# -----------------------
# Database Models
# -----------------------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)
    
    # Portfolio fields
    tagline = db.Column(db.String(150))
    bio = db.Column(db.Text)
    course = db.Column(db.String(100))
    faction = db.Column(db.String(50))
    avatar_url = db.Column(db.String(500))
    
    # Status & Socials
    status = db.Column(db.String(50))
    skills = db.Column(db.String(500))
    public_email = db.Column(db.String(120))
    linkedin = db.Column(db.String(200))
    github = db.Column(db.String(200))

    # --- START NEW CODE: Certifications Storage ---
    # We store the list of certs as a text string (JSON)
    certifications_data = db.Column(db.Text, default='[]')

    @property
    def certifications(self):
        """Returns the certifications as a Python list."""
        if not self.certifications_data:
            return []
        try:
            return json.loads(self.certifications_data)
        except:
            return []

    @certifications.setter
    def certifications(self, value):
        """Saves a Python list as a JSON string."""
        self.certifications_data = json.dumps(value)
    # --- END NEW CODE ---


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    image_file = db.Column(db.String(255))
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))


# -----------------------
# Login Manager
# -----------------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# -----------------------
# Helper Functions
# -----------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_picture(form_picture):
    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_picture.filename)
    picture_fn = random_hex + f_ext
    picture_path = os.path.join(app.root_path, 'static/uploads', picture_fn)
    form_picture.save(picture_path)
    return picture_fn


# -----------------------
# Routes
# -----------------------
@app.route('/')
def home():
    return render_template('home.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        existing = User.query.filter(
            (User.email == email) | (User.username == username)
        ).first()

        if existing:
            flash('User or email already exists.', 'danger')
            return redirect(url_for('register'))

        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        user = User(username=username, email=email, password=hashed)
        db.session.add(user)
        db.session.commit()

        flash('Registration successful. Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        pw = request.form['password']

        user = User.query.filter_by(email=email).first()

        if user and bcrypt.check_password_hash(user.password, pw):
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('dashboard'))

        flash('Invalid credentials.', 'danger')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out.', 'info')
    return redirect(url_for('home'))


@app.route('/dashboard')
@login_required
def dashboard():
    projects = Project.query.filter_by(user_id=current_user.id).all()
    return render_template('dashboard.html', projects=projects)


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.username = request.form.get('username')
        current_user.tagline = request.form.get('tagline')
        current_user.bio = request.form.get('bio')
        current_user.avatar_url = request.form.get('avatar_url')
        
        current_user.status = request.form.get('status')
        current_user.course = request.form.get('course')
        current_user.faction = request.form.get('faction')
        current_user.skills = request.form.get('skills')
        
        current_user.public_email = request.form.get('public_email')
        current_user.linkedin = request.form.get('linkedin')
        current_user.github = request.form.get('github')

        new_password = request.form.get('new_password')
        if new_password:
             current_user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')

        # --- START NEW CODE: Handle Dynamic Certifications ---
        cert_names = request.form.getlist('cert_name[]')
        cert_issuers = request.form.getlist('cert_issuer[]')
        cert_dates = request.form.getlist('cert_date[]')

        new_certs = []
        # Zip them together to handle them as sets
        for i in range(len(cert_names)):
            if cert_names[i].strip():  # Only save if name exists
                new_certs.append({
                    'name': cert_names[i],
                    'issuer': cert_issuers[i] if i < len(cert_issuers) else '',
                    'date': cert_dates[i] if i < len(cert_dates) else ''
                })
        
        # Save to database (the setter method handles the JSON conversion)
        current_user.certifications = new_certs
        # --- END NEW CODE ---

        try:
            db.session.commit()
            flash('Profile updated successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating profile: {e}', 'danger')
            
        return redirect(url_for('profile'))

    return render_template('profile.html', user=current_user)


@app.route('/projects', methods=['GET', 'POST'])
@login_required
def projects():
    if request.method == 'POST':
        title = request.form['title']
        desc = request.form['description']
        file = request.files['image']
        filename = None

        if file and allowed_file(file.filename):
            filename = save_picture(file)

        project = Project(
            title=title,
            description=desc,
            image_file=filename,
            user_id=current_user.id
        )
        db.session.add(project)
        db.session.commit()
        flash('Project added.', 'success')
        return redirect(url_for('projects'))

    projects = Project.query.filter_by(user_id=current_user.id).all()
    return render_template('projects.html', projects=projects)


@app.route('/projects/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_project(id):
    project = Project.query.get_or_404(id)
    if project.user_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('projects'))

    if request.method == 'POST':
        project.title = request.form['title']
        project.description = request.form['description']
        file = request.files.get('image')
        if file and file.filename != '':
            project.image_file = save_picture(file)
        
        db.session.commit()
        flash('Project updated.', 'success')
        return redirect(url_for('projects'))

    return render_template('edit_project.html', project=project)


@app.route('/projects/delete/<int:id>')
@login_required
def delete_project(id):
    project = Project.query.get_or_404(id)
    if project.user_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('projects'))

    db.session.delete(project)
    db.session.commit()
    flash('Project deleted.', 'info')
    return redirect(url_for('projects'))


@app.route('/portfolio/<username>')
def public_portfolio(username):
    user = User.query.filter_by(username=username).first()
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('home'))

    projects = Project.query.filter_by(user_id=user.id).all()
    return render_template('public_portfolio.html', user=user, projects=projects)


# --- PDF DOWNLOAD ROUTE ---
@app.route('/portfolio/<username>/download')
def download_portfolio(username):
    user = User.query.filter_by(username=username).first_or_404()
    projects = Project.query.filter_by(user_id=user.id).all()
    
    # Create Buffer
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    elements.append(Paragraph(f"{user.username}'s Portfolio", styles['Title']))
    elements.append(Spacer(1, 12))
    
    # Bio Section
    if user.course:
        elements.append(Paragraph(f"<b>Course:</b> {user.course}", styles['Normal']))
    if user.tagline:
        elements.append(Paragraph(f"<i>{user.tagline}</i>", styles['Normal']))
    if user.public_email:
        elements.append(Paragraph(f"<b>Email:</b> {user.public_email}", styles['Normal']))
    
    elements.append(Spacer(1, 20))
    
    # --- START NEW CODE: Add Certifications to PDF ---
    if user.certifications:
        elements.append(Paragraph("Certifications", styles['Heading2']))
        for cert in user.certifications:
             c_name = cert.get('name', 'Certification')
             c_issuer = cert.get('issuer', '')
             c_date = cert.get('date', '')
             elements.append(Paragraph(f"<b>{c_name}</b> - {c_issuer} ({c_date})", styles['Normal']))
        elements.append(Spacer(1, 20))
    # --- END NEW CODE ---

    # Projects Section
    elements.append(Paragraph("Projects", styles['Heading2']))
    
    for p in projects:
        elements.append(Paragraph(f"<b>{p.title}</b>", styles['Heading3']))
        if p.description:
            elements.append(Paragraph(p.description, styles['Normal']))
        elements.append(Spacer(1, 12))

    # Build PDF
    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"{user.username}_portfolio.pdf",
        mimetype='application/pdf'
    )


# -----------------------
# Run App & Create DB
# -----------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # This creates the tables if they don't exist
        print("Database tables created successfully!")

    app.run(debug=True)