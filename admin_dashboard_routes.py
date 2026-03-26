# from flask import request, render_template_string
# from flask_login import login_required
# import sqlite3, subprocess

# DB_PATH = "/app/instance/tender_analyzer.db"

# ADMIN_DASHBOARD_TEMPLATE = """
# <!doctype html>
# <html>
# <head>
#     <title>Admin Dashboard</title>
#     <style>
#         body { font-family: Arial, sans-serif; margin: 20px; }
#         textarea { width: 100%; height: 100px; }
#         table { border-collapse: collapse; width: 100%; margin-top: 10px; }
#         th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
#         th { background-color: #f2f2f2; }
#         pre { background: #f4f4f4; padding: 10px; border: 1px solid #ddd; white-space: pre-wrap; }
#         button { padding: 8px 16px; margin: 5px; }
#         h2 { color: #333; }
#         .tab { overflow: hidden; border-bottom: 1px solid #ccc; margin-bottom: 10px; }
#         .tab button { background: #f1f1f1; border: none; outline: none; cursor: pointer; padding: 10px 20px; transition: 0.3s; }
#         .tab button:hover { background: #ddd; }
#         .tab button.active { background: #ccc; }
#         .tabcontent { display: none; padding: 10px; }
#         .tabcontent.active { display: block; }
#     </style>
#     <script>
#         function openTab(evt, tabName) {
#             var i, tabcontent, tablinks;
#             tabcontent = document.getElementsByClassName("tabcontent");
#             for (i = 0; i < tabcontent.length; i++) {
#                 tabcontent[i].classList.remove("active");
#             }
#             tablinks = document.getElementsByClassName("tablink");
#             for (i = 0; i < tablinks.length; i++) {
#                 tablinks[i].classList.remove("active");
#             }
#             document.getElementById(tabName).classList.add("active");
#             if (evt) evt.currentTarget.classList.add("active");
#         }
#         window.onload = function() {
#             openTab(null, "{{ active_tab|default('SQLTab') }}");
#             document.getElementById("{{ active_tab|default('SQLTab') }}Btn").classList.add("active");
#         }
#     </script>
# </head>
# <body>
#     <h2>Admin Dashboard</h2>

#     <div class="tab">
#         <button id="SQLTabBtn" class="tablink" onclick="openTab(event, 'SQLTab')">SQLite Console</button>
#         <button id="SystemTabBtn" class="tablink" onclick="openTab(event, 'SystemTab')">Linux Status</button>
#     </div>

#     <div id="SQLTab" class="tabcontent">
#         <form method="post" action="{{ url_for('admin_dashboard_sql') }}">
#             <textarea name="sql" placeholder="Write your SQL here"></textarea><br>
#             <button type="submit">Run SQL</button>
#         </form>
#         {% if sql_result %}
#             <h4>SQL Result:</h4>
#             <div>{{ sql_result|safe }}</div>
#         {% endif %}
#     </div>

#     <div id="SystemTab" class="tabcontent">
#         <form method="post" action="{{ url_for('admin_dashboard_system') }}">
#             <button name="cmd" value="df -h">Disk Usage (df -h)</button>
#             <button name="cmd" value="free -m">Memory (free -m)</button>
#             <button name="cmd" value="uptime">Uptime</button>
#             <button name="cmd" value="top -bn1 | head -20">Top Processes</button>
#         </form>
#         {% if sys_result %}
#             <h4>System Result:</h4>
#             <pre>{{ sys_result }}</pre>
#         {% endif %}
#     </div>
# </body>
# </html>
# """

# def run_sql(query):
#     try:
#         conn = sqlite3.connect(DB_PATH)
#         cursor = conn.cursor()
#         cursor.execute(query)

#         if query.strip().lower().startswith("select"):
#             col_names = [desc[0] for desc in cursor.description]
#             rows = cursor.fetchall()

#             table_html = "<table>"
#             table_html += "<tr>" + "".join([f"<th>{col}</th>" for col in col_names]) + "</tr>"
#             for row in rows:
#                 table_html += "<tr>" + "".join([f"<td>{cell}</td>" for cell in row]) + "</tr>"
#             table_html += "</table>"

#             result = table_html
#         else:
#             conn.commit()
#             result = f"<p>Query executed. {cursor.rowcount} row(s) affected.</p>"

#         conn.close()
#         return result
#     except Exception as e:
#         return f"<p style='color:red;'>Error: {e}</p>"

# def run_cmd(cmd):
#     try:
#         output = subprocess.check_output(cmd, shell=True, text=True)
#         return output
#     except Exception as e:
#         return f"Error: {e}"

# def init_admin_dashboard_routes(app):
#     @app.route("/admin-dashboard", methods=["GET"])
#     @login_required
#     def admin_dashboard_home():
#         return render_template_string(ADMIN_DASHBOARD_TEMPLATE, active_tab="SQLTab")

#     @app.route("/admin-dashboard/sql", methods=["POST"])
#     @login_required
#     def admin_dashboard_sql():
#         sql = request.form.get("sql")
#         result = run_sql(sql)
#         return render_template_string(ADMIN_DASHBOARD_TEMPLATE, sql_result=result, active_tab="SQLTab")

#     @app.route("/admin-dashboard/system", methods=["POST"])
#     @login_required
#     def admin_dashboard_system():
#         cmd = request.form.get("cmd")
#         result = run_cmd(cmd)
#         return render_template_string(ADMIN_DASHBOARD_TEMPLATE, sys_result=result, active_tab="SystemTab")


from flask import request, render_template_string
from flask_login import login_required
from sqlalchemy import text
import subprocess
from models import db

ADMIN_DASHBOARD_TEMPLATE = """
<!doctype html>
<html>
<head>
    <title>Admin Dashboard</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        textarea { width: 100%; height: 100px; }
        table { border-collapse: collapse; width: 100%; margin-top: 10px; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
        pre { background: #f4f4f4; padding: 10px; border: 1px solid #ddd; white-space: pre-wrap; }
        button { padding: 8px 16px; margin: 5px; }
        h2 { color: #333; }
        .tab { overflow: hidden; border-bottom: 1px solid #ccc; margin-bottom: 10px; }
        .tab button { background: #f1f1f1; border: none; outline: none; cursor: pointer; padding: 10px 20px; transition: 0.3s; }
        .tab button:hover { background: #ddd; }
        .tab button.active { background: #ccc; }
        .tabcontent { display: none; padding: 10px; }
        .tabcontent.active { display: block; }
    </style>
    <script>
        function openTab(evt, tabName) {
            var i, tabcontent, tablinks;
            tabcontent = document.getElementsByClassName("tabcontent");
            for (i = 0; i < tabcontent.length; i++) {
                tabcontent[i].classList.remove("active");
            }
            tablinks = document.getElementsByClassName("tablink");
            for (i = 0; i < tablinks.length; i++) {
                tablinks[i].classList.remove("active");
            }
            document.getElementById(tabName).classList.add("active");
            if (evt) evt.currentTarget.classList.add("active");
        }
        window.onload = function() {
            openTab(null, "{{ active_tab|default('SQLTab') }}");
            document.getElementById("{{ active_tab|default('SQLTab') }}Btn").classList.add("active");
        }
    </script>
</head>
<body>
    <h2>Admin Dashboard</h2>

    <div class="tab">
        <button id="SQLTabBtn" class="tablink" onclick="openTab(event, 'SQLTab')">PostgreSQL Console</button>
        <button id="SystemTabBtn" class="tablink" onclick="openTab(event, 'SystemTab')">Linux Status</button>
    </div>

    <div id="SQLTab" class="tabcontent">
        <form method="post" action="{{ url_for('admin_dashboard_sql') }}">
            <textarea name="sql" placeholder="Write your SQL here"></textarea><br>
            <button type="submit">Run SQL</button>
        </form>
        {% if sql_result %}
            <h4>SQL Result:</h4>
            <div>{{ sql_result|safe }}</div>
        {% endif %}
    </div>

    <div id="SystemTab" class="tabcontent">
        <form method="post" action="{{ url_for('admin_dashboard_system') }}">
            <button name="cmd" value="df -h">Disk Usage (df -h)</button>
            <button name="cmd" value="free -m">Memory (free -m)</button>
            <button name="cmd" value="uptime">Uptime</button>
            <button name="cmd" value="top -bn1 | head -20">Top Processes</button>
            <button name="cmd" value="docker ps">Docker Containers</button>
            <button name="cmd" value="psql --version">PostgreSQL Version</button>
        </form>
        {% if sys_result %}
            <h4>System Result:</h4>
            <pre>{{ sys_result }}</pre>
        {% endif %}
    </div>
</body>
</html>
"""

def run_sql(query):
    try:
        if query.strip().lower().startswith("select"):
            result = db.session.execute(text(query))
            col_names = result.keys()
            rows = result.fetchall()

            table_html = "<table>"
            table_html += "<tr>" + "".join([f"<th>{col}</th>" for col in col_names]) + "</tr>"
            for row in rows:
                table_html += "<tr>" + "".join([f"<td>{cell}</td>" for cell in row]) + "</tr>"
            table_html += "</table>"

            return table_html
        else:
            # For non-SELECT queries (INSERT, UPDATE, DELETE, etc.)
            result = db.session.execute(text(query))
            db.session.commit()
            return f"<p>Query executed. {result.rowcount} row(s) affected.</p>"

    except Exception as e:
        db.session.rollback()
        return f"<p style='color:red;'>Error: {e}</p>"

def run_cmd(cmd):
    try:
        output = subprocess.check_output(cmd, shell=True, text=True)
        return output
    except Exception as e:
        return f"Error: {e}"

def init_admin_dashboard_routes(app):
    @app.route("/admin-dashboard", methods=["GET"])
    @login_required
    def admin_dashboard_home():
        return render_template_string(ADMIN_DASHBOARD_TEMPLATE, active_tab="SQLTab")

    @app.route("/admin-dashboard/sql", methods=["POST"])
    @login_required
    def admin_dashboard_sql():
        sql = request.form.get("sql")
        result = run_sql(sql)
        return render_template_string(ADMIN_DASHBOARD_TEMPLATE, sql_result=result, active_tab="SQLTab")

    @app.route("/admin-dashboard/system", methods=["POST"])
    @login_required
    def admin_dashboard_system():
        cmd = request.form.get("cmd")
        result = run_cmd(cmd)
        return render_template_string(ADMIN_DASHBOARD_TEMPLATE, sys_result=result, active_tab="SystemTab")