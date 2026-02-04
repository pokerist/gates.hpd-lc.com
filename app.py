import os
import re
import json
import base64
import requests
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from database import (
    init_db, get_person, create_person, create_entry, 
    block_person, unblock_person, get_all_persons, get_all_entries
)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'hyde_park_secret_key_2026_production')

# Support for reverse proxy with URL prefix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Configuration
APP_PREFIX = os.environ.get('APP_PREFIX', '/new')  # URL prefix for reverse proxy
PASSWORD = os.environ.get('GATE_PASSWORD', 'Smart@1150')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'
VISION_MODEL = 'qwen/qwen-vl-plus'
CAPTURES_DIR = 'static/captures'
DEBUG_MODE = os.environ.get('DEBUG', 'False').lower() == 'true'

# Ensure captures directory exists
os.makedirs(CAPTURES_DIR, exist_ok=True)

# Logging helper
def log(message):
    """Print log with timestamp"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {message}")

def extract_id_from_image(image_base64):
    """
    Extract Egyptian National ID information using OpenRouter Vision LLM.
    Returns dict with 'name' and 'id_number' keys.
    """
    log("=" * 80)
    log("🔍 بدء عملية استخراج البيانات من البطاقة")
    log("=" * 80)
    
    if not OPENROUTER_API_KEY:
        log("❌ خطأ: OPENROUTER_API_KEY غير موجود!")
        log("   يرجى تعيين المفتاح باستخدام: export OPENROUTER_API_KEY='your-key'")
        return {"id_number": "NOT_FOUND", "name": ""}
    
    log(f"✅ API Key موجود: {OPENROUTER_API_KEY[:20]}...")
    log(f"🤖 Model المستخدم: {VISION_MODEL}")
    log(f"🌐 Endpoint: {OPENROUTER_ENDPOINT}")
    
    # Prepare the prompt
    prompt = """You are reading an Egyptian National ID card.
Extract:
- Full name
- 14-digit national ID number

Return JSON only: { "name": "", "id_number": "" }
If the ID is unreadable, return { "id_number": "NOT_FOUND" }"""
    
    log("📝 Prompt المرسل للـ Vision Model:")
    log(f"   {prompt[:100]}...")
    
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
                            "url": f"data:image/jpeg;base64,{image_base64[:50]}..."
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
    
    log(f"📤 إرسال الطلب إلى OpenRouter...")
    log(f"   Temperature: {payload['temperature']}")
    log(f"   Max Tokens: {payload['max_tokens']}")
    
    try:
        response = requests.post(OPENROUTER_ENDPOINT, json=payload, headers=headers, timeout=30)
        
        log(f"📥 استلام الرد من OpenRouter")
        log(f"   Status Code: {response.status_code}")
        
        response.raise_for_status()
        
        result = response.json()
        log(f"✅ الرد الكامل من الـ Model:")
        log(f"   {json.dumps(result, indent=2, ensure_ascii=False)}")
        
        content = result['choices'][0]['message']['content']
        log(f"📄 المحتوى المستخرج: {content}")
        
        # Try to parse JSON from the response
        json_match = re.search(r'\{[^}]+\}', content)
        if json_match:
            data = json.loads(json_match.group())
            log(f"🔍 JSON المستخرج: {data}")
            
            # Validate ID number format (14 digits)
            id_number = data.get('id_number', 'NOT_FOUND')
            name = data.get('name', '').strip()
            
            log(f"👤 الاسم: {name}")
            log(f"🆔 رقم البطاقة: {id_number}")
            
            if id_number and re.match(r'^\d{14}$', id_number):
                log("✅ رقم البطاقة صحيح (14 رقم)")
                log("=" * 80)
                return {
                    "name": name,
                    "id_number": id_number
                }
            else:
                log(f"❌ رقم البطاقة غير صحيح: {id_number}")
                log("   يجب أن يكون 14 رقم بالضبط")
                log("=" * 80)
                return {"id_number": "NOT_FOUND", "name": ""}
        else:
            log("❌ لم يتم العثور على JSON في الرد")
            log("=" * 80)
            return {"id_number": "NOT_FOUND", "name": ""}
            
    except requests.exceptions.HTTPError as e:
        log(f"❌ خطأ HTTP من OpenRouter: {e}")
        log(f"   Response: {e.response.text if hasattr(e, 'response') else 'No response'}")
        log("=" * 80)
        return {"id_number": "NOT_FOUND", "name": ""}
    except Exception as e:
        log(f"❌ خطأ عام: {type(e).__name__}: {e}")
        log("=" * 80)
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
        
        log(f"💾 تم حفظ الصورة: {filepath}")
        return filename
    except Exception as e:
        log(f"❌ خطأ في حفظ الصورة: {e}")
        return None

@app.route('/')
def home():
    """Home page with Security/Admin buttons."""
    log("🏠 الصفحة الرئيسية")
    return render_template('home.html')

@app.route('/security')
def security():
    """Security screen with ID card scanner."""
    if not session.get('security_logged_in'):
        return redirect(url_for('security_login'))
    log("🔒 صفحة الأمن")
    return render_template('security.html')

@app.route('/security/login', methods=['GET', 'POST'])
def security_login():
    """Security login page."""
    if request.method == 'POST':
        password = request.form.get('password')
        if password == PASSWORD:
            session['security_logged_in'] = True
            log("✅ تسجيل دخول ناجح - Security")
            return redirect(url_for('security'))
        else:
            log("❌ محاولة تسجيل دخول فاشلة - Security")
            return render_template('login.html', error=True, page='Security', target='security_login')
    return render_template('login.html', page='Security', target='security_login')

@app.route('/security/logout')
def security_logout():
    """Security logout."""
    session.pop('security_logged_in', None)
    log("🚪 تسجيل خروج - Security")
    return redirect(url_for('home'))

@app.route('/admin')
def admin():
    """Admin screen with persons and entries management."""
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    log("⚙️ صفحة الإدارة")
    persons = get_all_persons()
    entries = get_all_entries()
    log(f"   عدد الأشخاص: {len(persons)}")
    log(f"   عدد السجلات: {len(entries)}")
    return render_template('admin.html', persons=persons, entries=entries)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page."""
    if request.method == 'POST':
        password = request.form.get('password')
        if password == PASSWORD:
            session['admin_logged_in'] = True
            log("✅ تسجيل دخول ناجح - Admin")
            return redirect(url_for('admin'))
        else:
            log("❌ محاولة تسجيل دخول فاشلة - Admin")
            return render_template('login.html', error=True, page='Admin', target='admin_login')
    return render_template('login.html', page='Admin', target='admin_login')

@app.route('/admin/logout')
def admin_logout():
    """Admin logout."""
    session.pop('admin_logged_in', None)
    log("🚪 تسجيل خروج - Admin")
    return redirect(url_for('home'))

@app.route('/verify', methods=['POST'])
def verify():
    """
    Verify ID card from captured image.
    Returns JSON with status and message.
    """
    log("\n" + "=" * 80)
    log("🎯 طلب جديد للتحقق من البطاقة")
    log("=" * 80)
    
    data = request.get_json()
    image_base64 = data.get('image', '')
    
    if not image_base64:
        log("❌ لم يتم إرسال صورة")
        return jsonify({"success": False, "message": "No image provided"}), 400
    
    log(f"📸 تم استلام صورة (حجم: {len(image_base64)} حرف)")
    
    # Remove data URL prefix if present
    if ',' in image_base64:
        image_base64 = image_base64.split(',')[1]
        log("✂️ تم إزالة data URL prefix")
    
    # Save the image
    saved_file = save_image(image_base64)
    
    # Extract ID information using Vision LLM
    extracted = extract_id_from_image(image_base64)
    id_number = extracted.get('id_number', 'NOT_FOUND')
    name = extracted.get('name', '')
    
    log(f"\n📊 نتيجة الاستخراج:")
    log(f"   الاسم: {name}")
    log(f"   رقم البطاقة: {id_number}")
    
    # Check if ID was successfully read
    if id_number == 'NOT_FOUND' or not id_number:
        log("❌ فشل قراءة البطاقة")
        log("=" * 80 + "\n")
        return jsonify({
            "success": False,
            "message": "❌ Could not read ID card. Please rescan.",
            "type": "error"
        })
    
    # Check if person exists in database
    person = get_person(id_number)
    
    if person is None:
        # New person - auto-create
        log(f"🆕 شخص جديد - سيتم إنشاء سجل")
        create_person(id_number, name)
        create_entry(name, id_number, 'NEW')
        log(f"✅ تم إنشاء سجل جديد للشخص: {name}")
        log(f"✅ تم تسجيل دخول جديد (NEW)")
        log("=" * 80 + "\n")
        return jsonify({
            "success": True,
            "message": f"✓ Welcome, {name}! Entry recorded.",
            "type": "success"
        })
    else:
        # Existing person - check if blocked
        log(f"👤 شخص موجود في قاعدة البيانات: {person['name']}")
        
        if person['is_blocked'] == 1:
            # Blocked - do NOT create entry
            log(f"🚫 الشخص محظور!")
            log(f"   السبب: {person['block_reason']}")
            log(f"❌ تم رفض الدخول")
            log("=" * 80 + "\n")
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
            log(f"✅ الشخص غير محظور - السماح بالدخول")
            create_entry(person['name'], id_number, 'ALLOWED')
            log(f"✅ تم تسجيل دخول (ALLOWED)")
            log("=" * 80 + "\n")
            return jsonify({
                "success": True,
                "message": f"✓ {person['name']} – Access granted.",
                "type": "success"
            })

@app.route('/block', methods=['POST'])
def block():
    """Block a person by ID number."""
    log("\n🚫 طلب حظر شخص")
    data = request.get_json()
    id_number = data.get('id_number', '')
    reason = data.get('reason', 'Administrative decision')
    
    if not id_number:
        log("❌ لم يتم تقديم رقم البطاقة")
        return jsonify({"success": False, "message": "No ID number provided"}), 400
    
    log(f"   رقم البطاقة: {id_number}")
    log(f"   السبب: {reason}")
    
    block_person(id_number, reason)
    log(f"✅ تم حظر الشخص بنجاح\n")
    return jsonify({"success": True, "message": f"Person {id_number} has been blocked."})

@app.route('/unblock', methods=['POST'])
def unblock():
    """Unblock a person by ID number."""
    log("\n✅ طلب إلغاء حظر شخص")
    data = request.get_json()
    id_number = data.get('id_number', '')
    
    if not id_number:
        log("❌ لم يتم تقديم رقم البطاقة")
        return jsonify({"success": False, "message": "No ID number provided"}), 400
    
    log(f"   رقم البطاقة: {id_number}")
    
    unblock_person(id_number)
    log(f"✅ تم إلغاء حظر الشخص بنجاح\n")
    return jsonify({"success": True, "message": f"Person {id_number} has been unblocked."})

if __name__ == '__main__':
    # Initialize database
    log("🚀 بدء تشغيل Hyde Park Gate System")
    log("=" * 80)
    log(f"🤖 Vision Model: {VISION_MODEL}")
    log(f"🌐 OpenRouter Endpoint: {OPENROUTER_ENDPOINT}")
    log(f"🔑 API Key: {'✅ موجود' if OPENROUTER_API_KEY else '❌ غير موجود'}")
    log(f"📁 مجلد حفظ الصور: {CAPTURES_DIR}")
    log(f"🔗 URL Prefix: {APP_PREFIX}")
    log(f"🛠️ Debug Mode: {DEBUG_MODE}")
    log("=" * 80 + "\n")
    
    init_db()
    
    # Run the app
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=DEBUG_MODE)
