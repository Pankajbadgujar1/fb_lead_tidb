from flask import Flask, request, jsonify
import json, os, requests, mysql.connector
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

@app.route('/api/webhook', methods=['GET'])
def verify():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')

    if mode == 'subscribe' and token == os.getenv('FB_VERIFY_TOKEN'):
        return challenge, 200
    return 'Forbidden', 403

@app.route('/api/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("Lead received:", json.dumps(data, indent=2))
    return jsonify({"success": True}), 200

if __name__ == '__main__':
    app.run(port=3000, debug=True)