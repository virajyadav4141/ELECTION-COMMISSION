from flask import Flask, render_template, request, redirect, session, send_file, jsonify
import sqlite3, random, io, csv
import psycopg2
import os
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    conn = psycopg2.connect(DATABASE_URL)
else:
    conn = psycopg2.connect(
        dbname="election",
        user="postgres",
        password="1234",
        host="localhost"
    )

conn.autocommit = True
cur = conn.cursor()
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
app.secret_key = "secret123"
DATABASE_URL = os.environ.get("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

def execute(q, p=()):
    cur.execute(q, p)

# -------- INIT DB --------
def init_db():

    execute("CREATE TABLE IF NOT EXISTS elections(id INTEGER PRIMARY KEY, name TEXT)")

    execute("""
    CREATE TABLE IF NOT EXISTS voters(
        id INTEGER PRIMARY KEY,
        name TEXT,
        unique_id TEXT,
        has_voted INTEGER DEFAULT 0,
        phase_id INTEGER,
        election_id INTEGER
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS candidates(
        id INTEGER PRIMARY KEY,
        name TEXT,
        position TEXT,
        photo TEXT,
        election_id INTEGER
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS duty_users(
        id INTEGER PRIMARY KEY,
        username TEXT,
        password TEXT
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS votes(
        id INTEGER PRIMARY KEY,
        voter_id INTEGER,
        candidate_id INTEGER,
        position TEXT,
        election_id INTEGER
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS phases(
        id INTEGER PRIMARY KEY,
        name TEXT,
        total_voters INTEGER,
        election_id INTEGER
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS positions(
        id INTEGER PRIMARY KEY,
        name TEXT,
        winners_count INTEGER,
        election_id INTEGER
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS evm_status(
        id INTEGER PRIMARY KEY,
        voter_id INTEGER,
        active INTEGER
    )
    """)

    execute("""
    INSERT INTO evm_status(id, voter_id, active)
    VALUES (1, NULL, 0)
    ON CONFLICT (id) DO NOTHING
    """)

    conn.commit()


init_db()

# -------- LOGIN --------
@app.route("/", methods=["GET","POST"])
def login():
    if request.method=="POST":
        if request.form["username"]=="admin" and request.form["password"]=="admin123":
            session.clear()
            session["admin"]=True
            return redirect("/admin")

        execute("SELECT * FROM duty_users WHERE username=%s AND password=%s",
                (request.form["username"], request.form["password"]))
        if cur.fetchone():
            session.clear()
            session["duty"]=True
            return redirect("/verify")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# -------- ADMIN --------
@app.route("/admin")
def admin():
    execute("SELECT * FROM elections")
    elections = cur.fetchall()

    if "election_id" not in session:
        return render_template("select_election.html", elections=elections)

    eid = session["election_id"]

    execute("SELECT * FROM candidates WHERE election_id=%s",(eid,))
    candidates = cur.fetchall()

    execute("SELECT * FROM positions WHERE election_id=%s",(eid,))
    positions = cur.fetchall()

    execute("SELECT COUNT(*) FROM voters WHERE election_id=%s",(eid,))
    total = cur.fetchone()[0]

    execute("SELECT COUNT(*) FROM voters WHERE has_voted=1 AND election_id=%s",(eid,))
    voted = cur.fetchone()[0]

    return render_template("admin.html",
                           candidates=candidates,
                           positions=positions,
                           total=total,
                           voted=voted,
                           remaining=total-voted)

# -------- ELECTION --------
@app.route("/create_election", methods=["POST"])
def create_election():
    execute("INSERT INTO elections(name) VALUES(%s)", (request.form["name"],))
    conn.commit()

    execute("SELECT id FROM elections ORDER BY id DESC LIMIT 1")
    session["election_id"] = cur.fetchone()[0]

    return redirect("/admin")

@app.route("/select_election/<int:id>")
def select_election(id):
    session["election_id"] = id
    return redirect("/admin")

@app.route("/delete_election/<int:id>")
def delete_election(id):
    execute("DELETE FROM voters WHERE election_id=%s",(id,))
    execute("DELETE FROM candidates WHERE election_id=%s",(id,))
    execute("DELETE FROM votes WHERE election_id=%s",(id,))
    execute("DELETE FROM positions WHERE election_id=%s",(id,))
    execute("DELETE FROM phases WHERE election_id=%s",(id,))
    execute("DELETE FROM elections WHERE id=%s",(id,))
    conn.commit()
    session.pop("election_id", None)
    return redirect("/admin")

# -------- POSITION --------
@app.route("/add_position", methods=["POST"])
def add_position():
    execute("INSERT INTO positions(name,winners_count,election_id) VALUES(%s,%s,%s)",
            (request.form["name"], request.form["winners"], session["election_id"]))
    conn.commit()
    return redirect("/admin")

@app.route("/delete_position/<int:id>")
def delete_position(id):
    execute("DELETE FROM positions WHERE id=%s",(id,))
    conn.commit()
    return redirect("/admin")

# -------- CANDIDATE --------
@app.route("/add_candidate", methods=["POST"])
def add_candidate():
    execute("INSERT INTO candidates(name,position,photo,election_id) VALUES(%s,%s,%s,%s)",
            (request.form["name"], request.form["position"], request.form["photo"], session["election_id"]))
    conn.commit()
    return redirect("/admin")

@app.route("/delete_candidate/<int:id>")
def delete_candidate(id):
    execute("DELETE FROM candidates WHERE id=%s",(id,))
    conn.commit()
    return redirect("/admin")

# -------- DUTY --------
@app.route("/add_duty", methods=["POST"])
def add_duty():
    execute("INSERT INTO duty_users(username,password) VALUES(%s,%s)",
            (request.form["username"], request.form["password"]))
    conn.commit()
    return redirect("/admin")

@app.route("/duty_list")
def duty_list():
    execute("SELECT * FROM duty_users")
    return render_template("duty_list.html", users=cur.fetchall())

# -------- SEARCH VOTER --------
@app.route("/search_voter", methods=["GET","POST"])
def search_voter():
    data=None
    if request.method=="POST":
        execute("SELECT * FROM voters WHERE unique_id=%s",(request.form["uid"],))
        data=cur.fetchone()
    return render_template("search.html", data=data)

# -------- EXPORT CSV --------
@app.route("/export_votes")
def export_votes():
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["Candidate","Position","Votes"])

    execute("""
    SELECT c.name,c.position,COUNT(v.id)
    FROM candidates c
    LEFT JOIN votes v ON c.id=v.candidate_id
    GROUP BY c.id
    """)

    for r in cur.fetchall():
        writer.writerow(r)

    output.seek(0)

    return send_file(io.BytesIO(output.getvalue().encode()),
                     mimetype="text/csv",
                     as_attachment=True,
                     download_name="votes.csv")

# -------- PHASE STATS --------
@app.route("/phase_stats")
def phase_stats():
    execute("""
    SELECT p.name, COUNT(v.id), SUM(v.has_voted)
    FROM phases p
    LEFT JOIN voters v ON p.id=v.phase_id
    GROUP BY p.id
    """)
    return render_template("phase_stats.html", data=cur.fetchall())

# -------- PHASE --------
@app.route("/create_phase", methods=["POST"])
def create_phase():
    execute("INSERT INTO phases(name,total_voters,election_id) VALUES(%s,%s,%s)",
            (request.form["name"], request.form["count"], session["election_id"]))
    conn.commit()

    execute("SELECT id FROM phases ORDER BY id DESC LIMIT 1")
    phase_id = cur.fetchone()[0]

    ids=[]
    for i in range(int(request.form["count"])):
        uid=str(random.randint(1000,9999))
        ids.append(uid)

        execute("INSERT INTO voters(name,unique_id,phase_id,election_id) VALUES(%s,%s,%s,%s)",
                (f"Student_{i+1}", uid, phase_id, session["election_id"]))

    conn.commit()

    buffer=io.BytesIO()
    doc=SimpleDocTemplate(buffer)
    styles=getSampleStyleSheet()

    elements=[Paragraph("Voter IDs", styles['Title'])]
    for i,uid in enumerate(ids):
        elements.append(Paragraph(f"{i+1}. {uid}", styles['Normal']))

    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name="voters.pdf")

# -------- VERIFY --------
@app.route("/verify", methods=["GET","POST"])
def verify():
    if request.method=="POST":
        execute("SELECT * FROM voters WHERE unique_id=%s",(request.form["uid"],))
        v=cur.fetchone()

        if v and not v[3]:
            execute("UPDATE evm_status SET voter_id=%s, active=1 WHERE id=1",(v[0],))
            conn.commit()
            return render_template("verify_success.html")

        return "Invalid"

    return render_template("verify.html")

# -------- EVM --------
@app.route("/evm")
def evm():
    return render_template("evm.html")

@app.route("/evm_check")
def evm_check():
    execute("SELECT voter_id,active FROM evm_status WHERE id=1")
    d=cur.fetchone()
    return jsonify({"status":"go","voter_id":d[0]}) if d[1]==1 else jsonify({"status":"wait"})

@app.route("/evm_vote/<int:voter_id>")
def evm_vote(voter_id):
    session["voter_id"]=voter_id
    execute("SELECT * FROM voters WHERE id=%s",(voter_id,))
    v=cur.fetchone()

    session["voter_name"]=v[1]
    session["election_id"]=v[5]

    return redirect("/vote")

# -------- VOTE --------
@app.route("/vote", methods=["GET","POST"])
def vote():
    if "voter_id" not in session:
        return redirect("/evm")

    if request.method=="POST":
        vid=session["voter_id"]

        for pos in request.form:
            execute("INSERT INTO votes(voter_id,candidate_id,position,election_id) VALUES(%s,%s,%s,%s)",
                    (vid, request.form[pos], pos, session["election_id"]))

        execute("UPDATE voters SET has_voted=1 WHERE id=%s",(vid,))
        execute("UPDATE evm_status SET voter_id=NULL, active=0 WHERE id=1")
        conn.commit()

        session.pop("voter_id", None)
        return redirect("/evm")

    execute("SELECT * FROM positions WHERE election_id=%s",(session["election_id"],))
    positions=cur.fetchall()

    execute("SELECT * FROM candidates WHERE election_id=%s",(session["election_id"],))
    candidates=cur.fetchall()

    return render_template("vote.html", positions=positions, candidates=candidates)

# -------- RUN --------
if __name__=="__main__":
    app.run(debug=True)
