import datetime
from flask import (
    render_template, request, redirect, url_for, flash, jsonify, session, current_app
)
from werkzeug.security import check_password_hash, generate_password_hash
import json 
import urllib.parse
from models import (
    db,
    Organization,
    User,
    Tender,
    Admin,
    GemTender,
    Constraint,
    ServiceProductDefinition,
    SearchConfiguration,
    NotificationRecipient,
    FeatureAccessControl
)
import logging
from threading import Thread
from functools import wraps
from flask_mail import Message
from database_config import engine
from sqlalchemy import text
from werkzeug.utils import secure_filename
from pathlib import Path
from load_gem_bid_details import run_gem_csv_import

# Import admin service and auth modules
import admin_services

def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Check if admin is logged in
        if 'admin_id' not in session:
            flash("Please log in as admin first", "warning")
            return redirect(url_for('admin_login'))
        
        return func(*args, **kwargs)
    return wrapper

ALLOWED_UPLOAD_EXTENSIONS = {"csv"}

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_UPLOAD_EXTENSIONS


def classify_uploaded_files(uploaded_files):
    # enforce exactly 2 files at classification level also (extra safety)
    valid_files = [f for f in uploaded_files if (f.filename or "").strip()]

    if len(valid_files) != 2:
        raise ValueError("Please upload exactly 2 CSV files.")

    bid_file = None
    financial_file = None

    for f in valid_files:
        original_name = (f.filename or "").strip()
        safe_name = secure_filename(original_name).lower()

        if not allowed_file(safe_name):
            raise ValueError(f"Invalid file type: {original_name}. Only CSV files are allowed.")

        #  use startswith (not "in")
        if safe_name.startswith("gem_bid_details"):
            bid_file = f
        elif safe_name.startswith("gem_financial_details"):
            financial_file = f

    if not bid_file or not financial_file:
        raise ValueError(
            "Upload must include 2 files starting with "
            "'gem_bid_details' and 'gem_financial_details'."
        )

    return bid_file, financial_file

def init_admin_dashboard_routes(app, mail):
    """
    Admin routes (session-based admin, uses session['admin_id']).
    """
    
    # Configure session timeout at app level
    # app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(minutes=30)
    # app.config['SESSION_COOKIE_NAME'] = 'admin_session'
    
    # ---------------- Admin login/logout ----------------
    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        if request.method == 'POST':
            email = request.form['email']
            password = request.form['password']
            admin = Admin.query.filter_by(email=email).first()
            if admin and check_password_hash(admin.password, password):
                session.permanent = True
                session['admin_id'] = admin.id
                admin.last_login = datetime.datetime.utcnow()
                db.session.commit()
                flash("Login successful!", "success")
                return redirect(url_for('organization'))
            flash("Invalid credentials", "danger")
            return render_template('admin_login.html')
        return render_template('admin_login.html')

    @app.route('/admin/logout')
    @admin_required
    def admin_logout():
        session.pop('admin_id', None)
        flash("Logged out successfully", "success")
        return redirect(url_for('admin_login'))

    @app.route('/admin/dashboard', methods=['GET', 'POST'])
    @admin_required
    def admin_dashboard_sql():
        admin = Admin.query.get(session['admin_id'])
        if request.method == 'POST':
            sql = request.form.get('sql')
            print(sql)

            result = admin_services.run_sql(sql)
            if "Error" in result:
                flash("Query contains blocked keywords or error occurred", "danger")
            else:
                flash("Query executed successfully", "success")
        else:
            result = None
        return render_template('admin.html', title="Admin Dashboard", admin=admin, sql_result=result, active_tab="SQLTab")

    @app.route("/admin-dashboard/system", methods=["POST"])
    @admin_required
    def admin_dashboard_system():
        cmd = request.form.get("cmd")
        result = admin_services.run_cmd(cmd)
        return render_template('admin.html', sys_result=result, active_tab="SystemTab")

    # ---------------- Organizations list ----------------
    @app.route('/admin/organization', methods=['GET'])
    @admin_required
    def organization():
        organizations = Organization.query.order_by(Organization.created_at.desc()).all()
        return render_template('admin_organization.html', 
                            mode='list', 
                            organizations=organizations)

    @app.route('/admin/organization/add', methods=['GET', 'POST'])
    @admin_required
    def add_organization():
        """
        Handles the creation of a new organization and all related entities (Users, 
        ServiceProductDefinitions, Constraints, and SearchConfigurations).
        """
        import re
        if request.method == "POST":
            # DEBUG: Print all form data
            print("=== DEBUG FORM DATA ===")
            for key in request.form:
                values = request.form.getlist(key)
                print(f"{key}: {values}")
            print("=======================")
            
            org_name = request.form.get("org_name")
            org_desc = request.form.get("org_description")

            if not org_name:
                flash("Organization name is required", "warning")
                return redirect(url_for("add_organization"))

            try:
                # ---------------------------------------
                # CREATE ORGANIZATION
                # ---------------------------------------
                org = Organization(name=org_name, description=org_desc or None)
                db.session.add(org)
                db.session.flush()

                # ---------------------------------------
                # USERS
                # ---------------------------------------
                usernames = request.form.getlist("users_username[]")
                emails = request.form.getlist("users_email[]")
                passwords = request.form.getlist("users_password[]")
                roles = request.form.getlist("users_role[]")

                org_admin_id = None
                created_users = []  # Store all created users

                for i in range(len(usernames)):
                    username = usernames[i].strip()
                    email = emails[i].strip()
                    password = passwords[i].strip()
                    role = roles[i].strip()

                    # Skip empty rows
                    if not username and not email:
                        continue

                    if not email:
                        flash(f"User #{i+1} skipped (email required)", "warning")
                        continue

                    # Validate email format
                    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                        flash(f"User #{i+1} skipped (invalid email)", "warning")
                        continue

                    hashed_password = generate_password_hash(password) 

                    user = User(
                        username=username if username else email.split('@')[0],  # default username from email
                        email=email,
                        password=hashed_password,
                        role=role,
                        organization_id=org.id
                    )

                    db.session.add(user)
                    db.session.flush()
                    
                    created_users.append(user)

                    # Store the FIRST admin user ID
                    if role == "admin" and org_admin_id is None:
                        org_admin_id = user.id

                # Validate at least one admin exists
                if not org_admin_id:
                    # Check if any user was created at all
                    if created_users:
                        # If no admin specified but users exist, make the first user admin
                        first_user = created_users[0]
                        first_user.role = "admin"
                        org_admin_id = first_user.id
                        flash("First user automatically assigned as admin (no admin specified)", "info")
                    else:
                        flash("At least one user (admin) is required", "danger")
                        db.session.rollback()
                        return redirect(url_for("add_organization"))

                # ---------------------------------------
                # SERVICE PRODUCT DEFINITIONS
                # ---------------------------------------
                definitions = request.form.getlist("services[]")
                
                # Only create service definitions if they exist
                if definitions and any(d.strip() for d in definitions):
                    for i in range(len(definitions)):
                        definition = definitions[i].strip()

                        if not definition:
                            continue

                        spd = ServiceProductDefinition(
                            definition=definition,
                            user_id=org_admin_id,
                            organization_id=org.id
                        )
                        db.session.add(spd)

                # ---------------------------------------
                # CONSTRAINTS
                # ---------------------------------------
                categories = request.form.getlist("constraint_category[]")
                descriptions = request.form.getlist("constraint_description[]")

                # Create constraints if they exist
                if descriptions and any(d.strip() for d in descriptions):
                    for i in range(len(categories)):
                        category = categories[i].strip()
                        description = descriptions[i].strip()

                        if not description:
                            continue

                        constraint = Constraint(
                            category=category if category else "General",  # default category
                            description=description,
                            user_id=org_admin_id,
                            organization_id=org.id
                        )
                        db.session.add(constraint)

                # ---------------------------------------
                # SEARCH CONFIGURATIONS
                # ---------------------------------------
                search_keywords = request.form.getlist("sc_keyword[]")
                max_tenders = request.form.getlist("sc_max[]")
                execution_times = request.form.getlist("sc_time[]")
                statuses = request.form.getlist("sc_active[]")
                recipients_json_list = request.form.getlist("sc_recipients_json[]")

                # Create search configurations if they exist
                if search_keywords and any(k.strip() for k in search_keywords):
                    for i in range(len(search_keywords)):
                        keyword = search_keywords[i].strip()

                        if not keyword:
                            continue

                        # Handle default values
                        max_t = max_tenders[i] if i < len(max_tenders) else 10
                        exec_time = execution_times[i] if i < len(execution_times) else "09:00"
                        active_status = statuses[i] if i < len(statuses) else "1"
                        
                        # The value from the form is recipients_json_list[i], which is URI encoded.
                        recipients_json_uri = recipients_json_list[i].strip() if i < len(recipients_json_list) else ""

                        search_config = SearchConfiguration(
                            search_keyword=keyword,
                            max_tenders=int(max_t) if max_t else 10,
                            execution_time=exec_time,
                            is_active=bool(int(active_status)) if active_status else True,
                            created_by=org_admin_id
                        )

                        db.session.add(search_config)
                        db.session.flush()

                        # Recipients for this search config
                        recipients = []
                        if recipients_json_uri:
                            try:
                                # 1. Decode the URI component
                                decoded_recipients_json = urllib.parse.unquote(recipients_json_uri)
                                # 2. Parse the decoded JSON string
                                recipients = json.loads(decoded_recipients_json)
                            except (json.JSONDecodeError, ValueError) as e:
                                flash(f"Error parsing recipients for search config '{keyword}': {str(e)}", "warning")
                        
                        # Add recipients
                        for r in range(len(recipients)):
                            rec = recipients[r]
                            name = rec.get("name", "").strip()
                            email = rec.get("email", "").strip()

                            if not name or not email:
                                continue  # skip broken rows

                            recipient = NotificationRecipient(
                                name=name,
                                email=email,
                                search_config_id=search_config.id
                            )
                            db.session.add(recipient)

                # ---------------------------------------
                # FINAL COMMIT
                # ---------------------------------------
                db.session.commit()

                flash(f"Organization '{org_name}' created successfully with {len(created_users)} user(s)!", "success")
                return redirect(url_for("organization"))

            except Exception as e:
                db.session.rollback()
                # It's helpful to see the exact error for debugging in the console
                print("Error creating organization:", str(e)) 
                flash(f"An error occurred while creating organization: {str(e)}", "danger")
                return redirect(url_for("add_organization"))

        # GET request - show the add organization form
        return render_template("admin_organization.html", mode='add')

    # ---------------- Manage Organization ---------------------
    @app.route('/admin/organization/<int:org_id>/manage', methods=['GET', 'POST'])
    @admin_required
    def manage_organization(org_id):
        if request.method == 'POST':
            form_type = request.form.get('form_type')
            
            if form_type == 'edit_organization':
                # Handle organization update
                org = Organization.query.get_or_404(org_id)
                org.name = request.form.get('org_name', '').strip()
                org.description = request.form.get('org_description', '').strip()
                
                if not org.name:
                    flash("Organization name is required", "danger")
                    return redirect(url_for('manage_organization', org_id=org_id))
                
                try:
                    db.session.commit()
                    flash('Organization updated successfully', 'success')
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error updating organization: {str(e)}', 'danger')
                
                return redirect(url_for('manage_organization', org_id=org_id))
                
            elif form_type == 'add_user':
                # Handle adding new user
                username = request.form.get('username', '').strip()
                email = request.form.get('email', '').strip()
                password = request.form.get('password', '').strip()
                role = request.form.get('role', 'user')
                
                if not username or not password:
                    flash("Username and password are required", "danger")
                    return redirect(url_for('manage_organization', org_id=org_id))
                
                # Check if username already exists
                existing_user = User.query.filter_by(username=username).first()
                if existing_user:
                    flash(f"Username '{username}' already exists", "danger")
                    return redirect(url_for('manage_organization', org_id=org_id))
                
                # Check if email already exists (if provided)
                if email:
                    existing_email = User.query.filter_by(email=email).first()
                    if existing_email:
                        flash(f"Email '{email}' already exists", "danger")
                        return redirect(url_for('manage_organization', org_id=org_id))
                
                try:
                    from werkzeug.security import generate_password_hash
                    user = User(
                        username=username,
                        email=email if email else None,
                        password=generate_password_hash(password),
                        role=role,
                        organization_id=org_id
                    )
                    db.session.add(user)
                    db.session.commit()
                    flash(f"User '{username}' added successfully", "success")
                except Exception as e:
                    db.session.rollback()
                    flash(f"Error adding user: {str(e)}", "danger")
                
                return redirect(url_for('manage_organization', org_id=org_id))
                
            elif form_type == 'edit_user':
                # Handle editing user
                user_id = request.form.get('user_id')
                if not user_id:
                    flash("User ID is required", "danger")
                    return redirect(url_for('manage_organization', org_id=org_id))
                
                success, org_id_from_user, message = admin_services.update_user(user_id, request.form)
                if success:
                    flash(message, "success")
                else:
                    flash(message, "danger")
                
                return redirect(url_for('manage_organization', org_id=org_id))
                
            elif form_type == 'delete_user':
                # Handle deleting user
                user_id = request.form.get('user_id')
                if not user_id:
                    flash("User ID is required", "danger")
                    return redirect(url_for('manage_organization', org_id=org_id))
                
                try:
                    user = User.query.get_or_404(user_id)
                    # Check if user belongs to this organization
                    if user.organization_id != org_id:
                        flash("User does not belong to this organization", "danger")
                        return redirect(url_for('manage_organization', org_id=org_id))
                    
                    username = user.username
                    db.session.delete(user)
                    db.session.commit()
                    flash(f"User '{username}' deleted successfully", "success")
                except Exception as e:
                    db.session.rollback()
                    flash(f"Error deleting user: {str(e)}", "danger")
                
                return redirect(url_for('manage_organization', org_id=org_id))
        
        # GET request - show the manage organization page
        data = admin_services.get_organization_management_data(org_id)
        return render_template('admin_organization.html',
                            mode='manage',
                            **data)
                            
    # ---------------- Manage tenders ----------------
    @app.route('/admin/manage-tenders')
    @admin_required
    def manage_tenders():
        tenders = GemTender.query.order_by(GemTender.id.desc()).all()
        organizations = Organization.query.all()
        return render_template('admin_manage_tenders.html', title="Manage Tenders", tenders=tenders, organizations=organizations)

    # ---------------- Analytics & Reports ------------------
    @app.route('/admin/analytics')
    @admin_required
    def analytics_reports():
        stats = admin_services.get_analytics_stats()
        return render_template('admin_analytics.html', 
                               title="Analytics & Reports",
                               **stats)

    # ---------------- Fetch GeM Tenders ----------------
    @app.route('/admin/fetch-gem')
    @admin_required
    def fetch_gem_page():
        return render_template('admin_fetch_tenders.html')
    
    @app.route('/fetch-gem-tenders', methods=['POST'])
    @admin_required
    def fetch_gem_tenders():
        success, result = admin_services.fetch_gem_tenders(request.json)
        if success:
            return jsonify(result), 200
        else:
            return jsonify(result), 400
        
    # ---------------- System Announcements ----------------
    @app.route('/admin/announcements', methods=['GET', 'POST'])
    @admin_required
    def system_announcements():

        if request.method == 'POST':
            subject = request.form.get('subject', '').strip()
            message = request.form.get('message', '').strip()

            if not subject or not message:
                print("[DEBUG] : Subject or message missing.", 'danger')
                flash('Subject and message are required.', 'danger')
                return redirect(url_for('system_announcements'))

            recipients = [
                user.email for user in User.query.all() if user.email
            ]

            if not recipients:
                print("[DEBUG] : No active users found to send announcement.", 'warning')
                flash('No active users found to send announcement.', 'warning')
                return redirect(url_for('system_announcements'))

            msg = Message(
                subject=subject,
                body=message,
                sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
                recipients=['243rushabh@gmail.com']  # hardcoded email for testing
            )

            try:
                mail.send(msg)
                print('[DEBUG] : Test announcement email sent successfully.', 'success')
                flash('Announcement sent successfully.', 'success')
                return redirect(url_for('system_announcements'))
            except Exception as e:
                current_app.logger.exception("Announcement email failed")
                flash('[DEBUG] : Email sending failed. Check server logs.', 'danger')

            return redirect(url_for('system_announcements'))

        return render_template('admin_announcements.html')

    @app.route('/admin/access-control', methods=['GET'])
    @admin_required
    def access_control():
        organizations = Organization.query.all()
        
        # Get all access controls
        controls = FeatureAccessControl.query.all()
        
        # Transform to dictionary with org_id as key and features as nested dict
        access_control = {}
        for control in controls:
            if control.organization_id not in access_control:
                access_control[control.organization_id] = {}
            access_control[control.organization_id][control.menu_item] = control.access
        
        return render_template('admin_access_control.html', 
                            organizations=organizations,
                            access_control=access_control)

    @app.route('/admin/update-access', methods=['POST'])
    @admin_required
    def update_access():
        data = request.get_json()
        org_id = data.get('organization_id')
        feature = data.get('feature')
        enabled = data.get('enabled')
        
        try:
            # Find existing control or create new one
            control = FeatureAccessControl.query.filter_by(
                organization_id=org_id, 
                menu_item=feature
            ).first()
            
            if not control:
                control = FeatureAccessControl(
                    organization_id=org_id,
                    menu_item=feature,
                    access=enabled
                )
                db.session.add(control)
            else:
                control.access = enabled
                
            db.session.commit()
            
            return jsonify({'success': True, 'message': f'Successfully updated {feature}'})

        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500

    @app.route("/admin/log-summary")
    @admin_required
    def log_summary():
        import datetime as dt

        organizations = Organization.query.order_by(Organization.name.asc()).all()

        sql = text("""
            SELECT r.*,
                o.name AS org_name
            FROM log_metrics r
            LEFT JOIN organization o ON o.id = r.org_id
            ORDER BY r.run_finished_at DESC NULLS LAST, r.id DESC
            LIMIT 500;
        """)

        with engine.begin() as conn:
            runs = conn.execute(sql).mappings().all()

        today = dt.date.today()

        prepared_runs = []
        today_total = 0
        today_completed = 0
        today_failed = 0
        today_attention = 0

        for r in runs:
            row = dict(r)

            duration_seconds = row.get("duration_seconds")
            if duration_seconds is None and row.get("run_started_at") and row.get("run_finished_at"):
                try:
                    duration_seconds = int((row["run_finished_at"] - row["run_started_at"]).total_seconds())
                    row["duration_seconds"] = duration_seconds
                except Exception:
                    duration_seconds = None

            if duration_seconds is not None:
                hh = duration_seconds // 3600
                mm = (duration_seconds % 3600) // 60
                ss = duration_seconds % 60
                row["duration_hms"] = f"{hh:02d}:{mm:02d}:{ss:02d}"
            else:
                row["duration_hms"] = None

            prepared_runs.append(row)

            rf = row.get("run_finished_at")
            if rf and hasattr(rf, "date") and rf.date() == today:
                today_total += 1

                status_val = (row.get("status") or "").upper()
                if status_val == "SUCCESS":
                    today_completed += 1
                elif status_val == "FAILED":
                    today_failed += 1

                if (row.get("flag_status") or "").upper() == "RED":
                    today_attention += 1

        return render_template(
            "log_summary.html",
            title="Log Summary | Admin",
            organizations=organizations,
            runs=prepared_runs,
            today_total=today_total,
            today_completed=today_completed,
            today_failed=today_failed,
            today_attention=today_attention,
            today_date=today.strftime("%Y-%m-%d"),
        )

    @app.route("/admin/log-summary/<int:run_id>/ack-flag", methods=["POST"])
    @admin_required
    def acknowledge_log_flag(run_id):
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE log_metrics
                    SET flag_status = 'YELLOW',
                        flag_acknowledged_at = NOW()
                    WHERE id = :run_id
                      AND flag_status = 'RED'
                """),
                {"run_id": run_id},
            )

        return jsonify({"success": True, "run_id": run_id, "flag_status": "YELLOW"})
    
    @app.route("/admin/upload")
    @admin_required
    def admin_upload_page():
        return render_template("admin_upload.html", title="Upload | Admin")


    @app.route("/admin/upload/gem-csv", methods=["POST"])
    @admin_required
    def upload_gem_csv():
        files = [f for f in request.files.getlist("files") if (f.filename or "").strip()]

        if len(files) != 2:
            flash("Please upload exactly 2 CSV files.", "danger")
            return redirect(url_for("admin_upload_page"))

        try:
            bid_file_obj, financial_file_obj = classify_uploaded_files(files)
            dry_run = request.form.get("dry_run") == "on"

            upload_dir = Path(app.config.get("UPLOAD_FOLDER", "/tmp")) / "admin_gem_uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)

            bid_path = upload_dir / secure_filename(bid_file_obj.filename)
            financial_path = upload_dir / secure_filename(financial_file_obj.filename)

            bid_file_obj.save(bid_path)
            financial_file_obj.save(financial_path)

            result = run_gem_csv_import(
                bid_file=bid_path,
                financial_file=financial_path,
                dry_run=dry_run,
            )

            if result["success"]:
                mode = "dry-run validation" if dry_run else "import"
                flash(f"GEM CSV {mode} completed successfully.", "success")
            else:
                flash(
                    f"GEM CSV import failed. "
                    f"Bid: {result.get('bid_status')}, "
                    f"Financial: {result.get('financial_status')}. "
                    f"{result.get('error', '')}",
                    "danger",
                )

        except Exception as e:
            app.logger.exception("Error during GEM CSV upload")
            flash(f"Upload failed: {str(e)}", "danger")

        return redirect(url_for("admin_upload_page"))