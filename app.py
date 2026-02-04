import os
import re
import json
import base64
import requests
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from database import (
    init_db, get_person, create_person, create_entry, 
    block_person, get_all_persons, get_all_entries
)

app = Flask(__name__)

# Configuration
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'
VISION_MODEL = 'qwen/qwen-vl-plus'
CAPTURES_DIR = 'static/captures'

# Ensure captures directory exists
os.makedirs(CAPTURES_DIR, exist_ok=True)

def extract_id_from_image(image_base64):
    """
    Extract Egyptian National ID information using OpenRouter Vision LLM.
    Returns dict with 'name' and 'id_number' keys.
    """
    if not OPENROUTER_API_KEY:
        return {"id_number": "NOT_FOUND", "name": ""}
    
    # Prepare the prompt
    prompt = """You are reading an Egyptian National ID card.
Extract:
- Full name
- 14-digit national ID number

Return JSON only: { "name": "", "id_number": "" }
If the ID is unreadable, return { "id_number": "NOT_FOUND" }"""
    
    # Prepare the request payload
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        }
                    }
                ]
            }
        ],
        "temperature": 0.1,
        "max_tokens": 200
    }
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(OPENROUTER_ENDPOINT, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        content = result['choices'][0]['message']['content']
        
        # Try to parse JSON from the response
        # Sometimes the model returns markdown code blocks, so we need to extract JSON
        json_match = re.search(r'\{[^}]+\}', content)
        if json_match:
            data = json.loads(json_match.group())
            
            # Validate ID number format (14 digits)
            id_number = data.get('id_number', 'NOT_FOUND')
            if id_number and re.match(r'^\d{14}$', id_number):
                return {
                    "name": data.get('name', '').strip(),
                    "id_number": id_number
                }
            else:
                return {"id_number": "NOT_FOUND", "name": ""}
        else:
            return {"id_number": "NOT_FOUND", "name": ""}
            
    except Exception as e:
        print(f"Error calling OpenRouter: {e}")
        return {"id_number": "NOT_FOUND", "name": ""}

def save_image(image_base64):
    """Save captured image to disk."""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}.jpg"
        filepath = os.path.join(CAPTURES_DIR, filename)
        
        # Decode and save
        image_data = base64.b64decode(image_base64)
        with open(filepath, 'wb') as f:
            f.write(image_data)
        
        return filename
    except Exception as e:
        print(f"Error saving image: {e}")
        return None

@app.route('/')
def home():
    """Home page with Security/Admin buttons."""
    return render_template('home.html')

@app.route('/security')
def security():
    """Security screen with ID card scanner."""
    return render_template('security.html')

@app.route('/admin')
def admin():
    """Admin screen with persons and entries management."""
    persons = get_all_persons()
    entries = get_all_entries()
    return render_template('admin.html', persons=persons, entries=entries)

@app.route('/verify', methods=['POST'])
def verify():
    """
    Verify ID card from captured image.
    Returns JSON with status and message.
    """
    data = request.get_json()
    image_base64 = data.get('image', '')
    
    if not image_base64:
        return jsonify({"success": False, "message": "No image provided"}), 400
    
    # Remove data URL prefix if present
    if ',' in image_base64:
        image_base64 = image_base64.split(',')[1]
    
    # Save the image
    save_image(image_base64)
    
    # Extract ID information using Vision LLM
    extracted = extract_id_from_image(image_base64)
    id_number = extracted.get('id_number', 'NOT_FOUND')
    name = extracted.get('name', '')
    
    # Check if ID was successfully read
    if id_number == 'NOT_FOUND' or not id_number:
        return jsonify({
            "success": False,
            "message": "❌ Could not read ID card. Please rescan.",
            "type": "error"
        })
    
    # Check if person exists in database
    person = get_person(id_number)
    
    if person is None:
        # New person - auto-create
        create_person(id_number, name)
        create_entry(name, id_number, 'NEW')
        return jsonify({
            "success": True,
            "message": f"✓ Welcome, {name}! Entry recorded.",
            "type": "success"
        })
    else:
        # Existing person - check if blocked
        if person['is_blocked'] == 1:
            # Blocked - do NOT create entry
            return jsonify({
                "success": False,
                "message": f"⚠️ ACCESS DENIED\n{person['name']} (ID: {id_number[:4]}...) is BLOCKED.\nReason: {person['block_reason']}\nContact admin.",
                "type": "blocked",
                "person": {
                    "name": person['name'],
                    "id_number": id_number,
                    "block_reason": person['block_reason']
                }
            })
        else:
            # Allowed - create entry
            create_entry(person['name'], id_number, 'ALLOWED')
            return jsonify({
                "success": True,
                "message": f"✓ {person['name']} – Access granted.",
                "type": "success"
            })

@app.route('/block', methods=['POST'])
def block():
    """Block a person by ID number."""
    data = request.get_json()
    id_number = data.get('id_number', '')
    reason = data.get('reason', 'Administrative decision')
    
    if not id_number:
        return jsonify({"success": False, "message": "No ID number provided"}), 400
    
    block_person(id_number, reason)
    return jsonify({"success": True, "message": f"Person {id_number} has been blocked."})

if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Run the app
    app.run(host='0.0.0.0', port=5000, debug=True)
