"""Local web dashboard: shows the bot's proposed trade (entry or exit) with
the reasoning behind it, and lets you Approve/Reject with one click.
Runs at http://localhost:5055 - only accessible on your machine by default."""

from flask import Flask, render_template, redirect, url_for

import state

app = Flask(__name__)


@app.route("/")
def index():
    s = state.load()
    return render_template("index.html", s=s)


@app.route("/approve-entry", methods=["POST"])
def approve_entry():
    state.update(decision="approved")
    return redirect(url_for("index"))


@app.route("/reject-entry", methods=["POST"])
def reject_entry():
    state.update(decision="rejected")
    return redirect(url_for("index"))


@app.route("/approve-exit", methods=["POST"])
def approve_exit():
    state.update(exit_decision="approved")
    return redirect(url_for("index"))


@app.route("/reject-exit", methods=["POST"])
def reject_exit():
    state.update(exit_decision="rejected")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5055, debug=False)
