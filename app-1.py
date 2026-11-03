from flask import Flask, request, jsonify, send_from_directory

import config

app = Flask(__name__, static_folder='static', static_url_path='')

@app.route('/')
def index():
    return send_from_directory("static", "index.html")

@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    # 会话功能
    return jsonify([])

@app.route('/api/documents', methods=['GET'])
def list_documents():
    # 文档功能
    return jsonify([])

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8000, debug=True)