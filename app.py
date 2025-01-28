import os
from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
import cv2
from skimage.metrics import structural_similarity as ssim

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Predefined Admin Credentials
ADMIN_MOBILE = '9999999999'
ADMIN_PASSWORD = bcrypt.generate_password_hash('admin123').decode('utf-8')

# User Model
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    mobile = db.Column(db.String(15), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    points = db.Column(db.Integer, default=0)
    images = db.relationship('Image', backref='user', lazy=True)

# Image Model
class Image(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default="pending")
    credited = db.Column(db.Boolean, default=False)  # To prevent duplicate points

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Home Route
@app.route('/')
def home():
    return render_template('home.html')

# Register Route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        mobile = request.form['mobile']
        password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')

        # Prevent duplicate mobile numbers
        if User.query.filter_by(mobile=mobile).first():
            flash('Mobile number already registered!', 'danger')
            return redirect(url_for('register'))

        new_user = User(name=name, mobile=mobile, password=password)
        db.session.add(new_user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

# Login Route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        mobile = request.form['mobile']
        password = request.form['password']
        user = User.query.filter_by(mobile=mobile).first()

        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials!', 'danger')

    return render_template('login.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        mobile = request.form['mobile']
        password = request.form['password']

        if mobile == ADMIN_MOBILE and bcrypt.check_password_hash(ADMIN_PASSWORD, password):
            admin = User.query.filter_by(mobile=ADMIN_MOBILE).first()

            if not admin:
                admin = User(name='Admin', mobile=ADMIN_MOBILE, password=ADMIN_PASSWORD, is_admin=True)
                db.session.add(admin)
                db.session.commit()

            login_user(admin)
            return redirect(url_for('admin_dashboard'))

        flash('Invalid Admin Credentials!', 'danger')

    return render_template('admin_login.html')

# User Dashboard
@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user)

# Image Upload Route
@app.route('/upload', methods=['POST'])
@login_required
def upload():
    if 'file' not in request.files:
        flash('No file part', 'danger')
        return redirect(url_for('dashboard'))

    file = request.files['file']

    if file.filename == '':
        flash('No selected file', 'danger')
        return redirect(url_for('dashboard'))

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    new_image = Image(user_id=current_user.id, filename=filename)
    db.session.add(new_image)
    db.session.commit()

    flash('Image uploaded successfully!', 'success')
    return redirect(url_for('dashboard'))

# Admin Dashboard Route
@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return redirect(url_for('login'))
    
    # Retrieve the current reference image, if exists
    admin_reference_image = os.path.join(app.config['UPLOAD_FOLDER'], 'admin_reference.jpg')
    return render_template('admin_dashboard.html', admin_reference_image=admin_reference_image)

@app.route('/admin/upload_reference', methods=['GET', 'POST'])
@login_required
def admin_upload_reference_image():
    if not current_user.is_admin:
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        file = request.files['file']

        if not file or file.filename == '':
            flash('No file selected!', 'danger')
            return redirect(url_for('upload_reference_image'))

        # Save the admin reference image to a fixed location in the static folder
        filename = secure_filename(file.filename)
        admin_image_path = os.path.join(app.config['UPLOAD_FOLDER'], 'admin_reference.jpg')
        file.save(admin_image_path)

        flash('Admin reference image updated successfully!', 'success')
        return redirect(url_for('admin_dashboard'))  # Redirect to the admin dashboard after upload

    return render_template('admin_upload_reference.html')

# SSIM-Based Image Comparison (with admin-uploaded reference image)
def compare_images(image1_path, image2_path):
    img1 = cv2.imread(image1_path, cv2.IMREAD_GRAYSCALE)
    img2 = cv2.imread(image2_path, cv2.IMREAD_GRAYSCALE)

    if img1 is None or img2 is None:
        return 0  # Return 0 similarity if images are missing

    img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
    score, _ = ssim(img1, img2, full=True)
    return score

@app.route('/admin/compare_images', methods=['POST'])
@login_required
def admin_compare_images():
    if not current_user.is_admin:
        return redirect(url_for('admin_login'))

    # Use the updated admin reference image
    admin_image_path = os.path.join(app.config['UPLOAD_FOLDER'], 'admin_reference.jpg')

    # Check if the reference image exists before proceeding
    if not os.path.exists(admin_image_path):
        flash('Admin reference image not found. Please upload a reference image first.', 'danger')
        return redirect(url_for('upload_reference_image'))

    similar_images = []
    non_similar_images = []

    users = User.query.all()

    for user in users:
        for image in user.images:
            if image.status != 'denied':  # Skip denied images
                user_image_path = os.path.join(app.config['UPLOAD_FOLDER'], image.filename)

                # Compare the images using SSIM
                similarity_score = compare_images(admin_image_path, user_image_path)

                # Categorize based on similarity score
                if similarity_score > 0.75:
                    similar_images.append({
                        'image': image,
                        'user': user,
                        'similarity_score': similarity_score
                    })
                else:
                    non_similar_images.append({
                        'image': image,
                        'user': user,
                        'similarity_score': similarity_score
                    })
                    # Update the status to 'denied' for non-similar images
                    image.status = 'denied'
                    db.session.commit()

    return render_template('admin_compare_images.html', similar_images=similar_images, non_similar_images=non_similar_images)

# Admin Assign Credits to Similar Images
@app.route('/admin/assign_credits', methods=['POST'])
@login_required
def admin_assign_credits():
    if not current_user.is_admin:
        return redirect(url_for('admin_login'))

    credits = int(request.form['credits'])
    selected_image_ids = request.form.getlist('selected_images')

    # Deny all images that are not selected for credit
    for image_id in selected_image_ids:
        image = Image.query.get(image_id)
        if image and not image.credited:
            image.credited = True
            image.status = 'accepted'
            image.user.points += credits  # Add points to the user
            db.session.commit()

    # Deny all images that are not selected
    all_images = Image.query.all()
    for image in all_images:
        if image.id not in [int(img_id) for img_id in selected_image_ids]:
            image.status = 'denied'
            db.session.commit()

    flash('Credits assigned successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

# Logout Route
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
