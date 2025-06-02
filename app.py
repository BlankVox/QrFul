import os
from flask import Flask, render_template, request, redirect, url_for, send_file, session, flash
from werkzeug.utils import secure_filename
import qrcode
import io
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from config import Config
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['QRCODE_FOLDER'] = os.path.join('static', 'qrcodes')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['QRCODE_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'txt', 'doc', 'docx'}

# User model
default_avatar = 'static/icons/default_avatar.png'
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    avatar = db.Column(db.String(256), default=default_avatar)
    histories = db.relationship('UserHistory', backref='user', lazy=True)

class UserHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(16))
    value = db.Column(db.String(512))
    qr = db.Column(db.String(256))
    file_link = db.Column(db.String(512))
    time = db.Column(db.String(64))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Flask-WTF Forms
class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Username already exists.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Email already registered.')

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

# Session-based QR code history for guests
@app.before_request
def make_session_permanent():
    session.permanent = True
    if 'history' not in session:
        session['history'] = []

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_qr_code(img):
    filename = f"qr_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}.png"
    path = os.path.join(app.config['QRCODE_FOLDER'], filename)
    img.save(path, format='PNG')
    return filename

@app.route('/', methods=['GET', 'POST'])
def index():
    qr_code_filename = None
    file_link = None
    if request.method == 'POST':
        data = request.form.get('data')
        file = request.files.get('file')
        fg_color = request.form.get('fg_color', '#22223b')
        bg_color = request.form.get('bg_color', '#ffffff')
        if data:
            qr = qrcode.QRCode(box_size=10, border=4)
            qr.add_data(data)
            qr.make(fit=True)
            img = qr.make_image(fill_color=fg_color, back_color=bg_color)
            qr_code_filename = save_qr_code(img)
            if current_user.is_authenticated:
                hist = UserHistory(user_id=current_user.id, type='text', value=data, qr=qr_code_filename, time=str(datetime.now()))
                db.session.add(hist)
                db.session.commit()
            else:
                session['history'].append({'type': 'text', 'value': data, 'qr': qr_code_filename, 'time': str(datetime.now())})
        elif file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            download_url = url_for('uploaded_file', filename=filename, _external=True)
            qr = qrcode.QRCode(box_size=10, border=4)
            qr.add_data(download_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color=fg_color, back_color=bg_color)
            qr_code_filename = save_qr_code(img)
            file_link = download_url
            if current_user.is_authenticated:
                hist = UserHistory(user_id=current_user.id, type='file', value=filename, qr=qr_code_filename, file_link=file_link, time=str(datetime.now()))
                db.session.add(hist)
                db.session.commit()
            else:
                session['history'].append({'type': 'file', 'value': filename, 'qr': qr_code_filename, 'file_link': file_link, 'time': str(datetime.now())})
        else:
            flash('Please enter text/link or upload a valid file.')
        session.modified = True
        if qr_code_filename:
            return render_template('index.html', qr_code_filename=qr_code_filename, file_link=file_link)
    return render_template('index.html')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename), as_attachment=True)

@app.route('/qrcodes/<filename>')
def qr_code_file(filename):
    return send_file(os.path.join(app.config['QRCODE_FOLDER'], filename), as_attachment=True)

@app.route('/history')
def history():
    if current_user.is_authenticated:
        user_history = UserHistory.query.filter_by(user_id=current_user.id).order_by(UserHistory.id.desc()).all()
        return render_template('history.html', history=user_history)
    else:
        return render_template('history.html', history=session.get('history', []))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_pw = generate_password_hash(form.password.data)
        user = User(username=form.username.data, email=form.email.data, password_hash=hashed_pw)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/reader')
def reader():
    return render_template('qr_reader.html')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True) 