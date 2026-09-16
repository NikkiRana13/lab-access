"""
photo_upload.py - tiny standalone local tool, unrelated to the LAB ACCESS
Arduino dashboard. It's just a webpage where you can pick or drag-and-drop
a photo, which gets saved to disk at a fixed path so it's easy to point
someone (or Claude) at afterward.

Run:
    python3 photo_upload.py

Then open http://localhost:5051, upload a photo, and it's saved as
uploads/upload.<ext> - overwriting any previous upload, so there's always
exactly one file to look at.
"""

import os

from flask import Flask, redirect, request, send_from_directory

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}

app = Flask(__name__)
os.makedirs(UPLOAD_DIR, exist_ok=True)


def find_existing_upload():
    for name in os.listdir(UPLOAD_DIR):
        if name.startswith("upload."):
            return name
    return None


@app.route("/", methods=["GET"])
def index():
    existing = find_existing_upload()
    preview_html = ""
    if existing:
        preview_html = f"""
          <h2>Current photo</h2>
          <img src="/uploads/{existing}" alt="uploaded photo" />
          <p class="path">Saved at: uploads/{existing}</p>
        """

    return f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8" />
      <title>Photo Upload</title>
      <style>
        body {{ font-family: -apple-system, sans-serif; max-width: 480px; margin: 60px auto; padding: 0 20px; color: #111; }}
        h1 {{ font-size: 20px; }}
        .dropzone {{
          display: block; border: 2px dashed #aaa; border-radius: 12px; padding: 40px 20px;
          text-align: center; color: #666; cursor: pointer; margin-bottom: 24px;
        }}
        .dropzone.dragover {{ border-color: #007faf; background: #f0f8fb; }}
        img {{ max-width: 100%; border-radius: 8px; border: 1px solid #ddd; }}
        .path {{ font-size: 12px; color: #888; font-family: monospace; }}
        input[type=file] {{ display: none; }}
      </style>
    </head>
    <body>
      <h1>Upload a photo</h1>
      <form id="uploadForm" method="POST" enctype="multipart/form-data">
        <label class="dropzone" id="dropzone" for="fileInput">
          Click to choose a photo, or drag one here
        </label>
        <input type="file" id="fileInput" name="photo" accept="image/*" />
      </form>
      {preview_html}
      <script>
        const form = document.getElementById('uploadForm');
        const input = document.getElementById('fileInput');
        const dropzone = document.getElementById('dropzone');

        input.addEventListener('change', () => {{ if (input.files.length) form.submit(); }});

        ['dragover', 'dragenter'].forEach(evt =>
          dropzone.addEventListener(evt, e => {{ e.preventDefault(); dropzone.classList.add('dragover'); }})
        );
        ['dragleave', 'drop'].forEach(evt =>
          dropzone.addEventListener(evt, e => {{ e.preventDefault(); dropzone.classList.remove('dragover'); }})
        );
        dropzone.addEventListener('drop', e => {{
          if (e.dataTransfer.files.length) {{
            input.files = e.dataTransfer.files;
            form.submit();
          }}
        }});
      </script>
    </body>
    </html>
    """


@app.route("/", methods=["POST"])
def upload():
    file = request.files.get("photo")
    if not file or file.filename == "":
        return redirect("/")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return "Unsupported file type.", 400

    # Remove any previous upload so there's always exactly one file here.
    for name in os.listdir(UPLOAD_DIR):
        if name.startswith("upload."):
            os.remove(os.path.join(UPLOAD_DIR, name))

    file.save(os.path.join(UPLOAD_DIR, f"upload.{ext}"))
    return redirect("/")


@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)


if __name__ == "__main__":
    print(f"Photo upload tool running - saves to {UPLOAD_DIR}")
    print("Open http://localhost:5051 in your browser.")
    app.run(host="127.0.0.1", port=5051, debug=False)
